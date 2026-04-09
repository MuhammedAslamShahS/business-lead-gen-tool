#!/usr/bin/env python3
"""
Simple local lead generation web app with MongoDB upload support.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import List

from flask import Flask, jsonify, render_template, request
from pymongo import MongoClient, UpdateOne
from pymongo.errors import PyMongoError

from lead_service import Business, collect_businesses, make_dedupe_key, write_output


APP_ROOT = Path(__file__).resolve().parent
DETAILS_PATH = APP_ROOT / "details.txt"
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "leadgen_DB"
COLLECTION_NAME = "business_leads"

app = Flask(__name__)


def get_collection():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    db = client[DB_NAME]
    collection = db[COLLECTION_NAME]
    collection.create_index("dedupe_key", unique=True)
    return client, collection


def business_from_payload(payload: dict) -> Business:
    socials = payload.get("socials") or {}
    name = payload.get("name", "Not available")
    location = payload.get("location", "Not available")
    return Business(
        name=name,
        location=location,
        phone=payload.get("phone", "Not available"),
        email=payload.get("email", "Not available"),
        website=payload.get("website", "Not available"),
        socials={
            "Facebook": socials.get("Facebook", "Not available"),
            "Instagram": socials.get("Instagram", "Not available"),
            "LinkedIn": socials.get("LinkedIn", "Not available"),
            "X/Twitter": socials.get("X/Twitter", "Not available"),
            "YouTube": socials.get("YouTube", "Not available"),
        },
        source_urls=payload.get("source_urls") or [],
        source_location=payload.get("source_location", ""),
        dedupe_key=make_dedupe_key(name, location),
    )


def normalize_filter_value(value: str) -> str:
    return (value or "").strip()


def build_saved_leads_query(filters: dict) -> dict:
    conditions = []
    field_map = {
        "country": [
            "search_location_parts.country",
            "source_location",
            "location",
        ],
        "state": [
            "search_location_parts.state",
            "source_location",
            "location",
        ],
        "district": [
            "search_location_parts.district",
            "source_location",
            "location",
        ],
        "city": [
            "search_location_parts.city",
            "source_location",
            "location",
        ],
        "location": [
            "search_display_location",
            "source_location",
            "location",
        ],
    }

    for key, fields in field_map.items():
        value = normalize_filter_value(filters.get(key, ""))
        if not value:
            continue
        conditions.append(
            {
                "$or": [
                    {field: {"$regex": value, "$options": "i"}}
                    for field in fields
                ]
            }
        )

    return {"$and": conditions} if conditions else {}


def fetch_saved_leads(filters: dict | None = None):
    client = None
    try:
        client, collection = get_collection()
        query = build_saved_leads_query(filters or {})
        documents = list(
            collection.find(query, {"_id": 0}).sort(
                [("created_at", -1), ("name", 1)]
            )
        )
        for document in documents:
            created_at = document.get("created_at")
            if created_at is not None:
                document["created_at_display"] = created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
            else:
                document["created_at_display"] = "Not available"
        return documents, None
    except PyMongoError as exc:
        return [], f"Could not load saved leads: {exc}"
    finally:
        if client is not None:
            client.close()


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/alleads")
def all_leads_page():
    filters = {
        "country": normalize_filter_value(request.args.get("country", "")),
        "state": normalize_filter_value(request.args.get("state", "")),
        "district": normalize_filter_value(request.args.get("district", "")),
        "city": normalize_filter_value(request.args.get("city", "")),
        "location": normalize_filter_value(request.args.get("location", "")),
    }
    leads, error = fetch_saved_leads(filters)
    return render_template("alleads.html", leads=leads, error=error, filters=filters)


@app.get("/api/alleads")
def all_leads_api():
    filters = {
        "country": normalize_filter_value(request.args.get("country", "")),
        "state": normalize_filter_value(request.args.get("state", "")),
        "district": normalize_filter_value(request.args.get("district", "")),
        "city": normalize_filter_value(request.args.get("city", "")),
        "location": normalize_filter_value(request.args.get("location", "")),
    }
    leads, error = fetch_saved_leads(filters)
    if error:
        return jsonify({"error": error}), 500
    return jsonify({"count": len(leads), "filters": filters, "results": leads})


@app.post("/api/search")
def search_leads():
    payload = request.get_json(silent=True) or {}
    location = (payload.get("location") or "").strip()
    country = (payload.get("country") or "").strip()
    state = (payload.get("state") or "").strip()
    district = (payload.get("district") or "").strip()
    city = (payload.get("city") or "").strip()
    limit = payload.get("limit", 8)

    try:
        limit = max(1, min(100, int(limit)))
    except (TypeError, ValueError):
        return jsonify({"error": "Limit must be a number."}), 400

    if not any([location, country, state, district, city]):
        return jsonify({"error": "Enter at least one location field."}), 400

    try:
        location_query, businesses = collect_businesses(
            location=location,
            country=country,
            state=state,
            district=district,
            city=city,
            limit=limit,
            delay_seconds=0.05,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Search failed: {exc}"}), 500

    write_output(str(DETAILS_PATH), businesses)
    return jsonify(
        {
            "location": location_query.display_name,
            "location_parts": {
                "country": location_query.parts.country,
                "state": location_query.parts.state,
                "district": location_query.parts.district,
                "city": location_query.parts.city,
            },
            "limit": limit,
            "count": len(businesses),
            "details_file": str(DETAILS_PATH),
            "results": [business.to_dict() for business in businesses],
        }
    )


@app.post("/api/upload")
def upload_leads():
    payload = request.get_json(silent=True) or {}
    leads_payload = payload.get("leads") or []
    if not isinstance(leads_payload, list) or not leads_payload:
        return jsonify({"error": "No leads were provided for upload."}), 400

    leads: List[Business] = [business_from_payload(item) for item in leads_payload]
    unique_keys = sorted({lead.dedupe_key for lead in leads if lead.dedupe_key})
    now = datetime.now(timezone.utc)
    operations = []
    for lead, original_payload in zip(leads, leads_payload):
        operations.append(
            UpdateOne(
                {"dedupe_key": lead.dedupe_key},
                {
                    "$setOnInsert": {
                        **lead.to_dict(),
                        "search_location_parts": original_payload.get("search_location_parts", {}),
                        "search_display_location": original_payload.get("search_display_location", ""),
                        "created_at": now,
                    }
                },
                upsert=True,
            )
        )

    client = None
    try:
        client, collection = get_collection()
        existing_count = collection.count_documents({"dedupe_key": {"$in": unique_keys}})
        result = collection.bulk_write(operations, ordered=False)
        inserted_count = result.upserted_count
        skipped_count = max(existing_count, len(unique_keys) - inserted_count)
        return jsonify(
            {
                "inserted": inserted_count,
                "skipped_existing": skipped_count,
                "database": DB_NAME,
                "collection": COLLECTION_NAME,
            }
        )
    except PyMongoError as exc:
        return jsonify({"error": f"MongoDB upload failed: {exc}"}), 500
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
    host = os.getenv("LEADGEN_HOST", "127.0.0.1")
    port = int(os.getenv("LEADGEN_PORT", "5000"))
    app.run(debug=debug_mode, host=host, port=port)
