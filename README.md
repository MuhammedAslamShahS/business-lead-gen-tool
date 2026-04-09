# LeadGen Tool

A clean local lead-generation web app for discovering publicly available business details, reviewing generated leads, and saving only new records into MongoDB.

## Overview

LeadGen Tool helps you:

- Search businesses by structured location fields
- Generate lead data from public sources only
- Review generated results in a table
- Keep generated results visible on refresh before uploading
- Search generated leads live with suggestion dropdowns
- Upload only non-duplicate records into MongoDB
- Browse and filter saved leads from the database

## Key Features

- Structured search fields:
  - `Country`
  - `State / Province`
  - `District / Neighborhood`
  - `City`
  - `Limit`
- Public-data-only lead collection
- Generated lead table with:
  - Business name
  - Location
  - Phone
  - Email
  - Website
  - Social media links
- Frontend persistence:
  - Generated data remains visible after page refresh
- Live search on generated data:
  - Search by business name
  - Search by phone number
  - Search by location
  - Suggestion dropdown while typing
- MongoDB upload with duplicate protection
- `All Leads` page with filter system:
  - Country filter
  - State / Province filter
  - District / Neighborhood filter
  - City filter
  - Location text filter

## Tech Stack

- Python 3.14
- Flask
- PyMongo
- MongoDB Local
- HTML
- CSS
- Vanilla JavaScript

## Data Policy

This project is designed to use only publicly visible information from:

- Official business websites
- Public business directories
- Public profiles

It does not use:

- Private data
- Login-only pages
- Hidden or protected sources

## Project Structure

```text
leadgen-tool/
├─ app.py
├─ lead_service.py
├─ collect_miami_business_details.py
├─ requirements.txt
├─ details.txt
├─ README.md
├─ templates/
│  ├─ index.html
│  └─ alleads.html
└─ static/
   ├─ styles.css
   └─ app.js
```

## How It Works

### 1. Search Leads

From the home page, enter your location details and limit.  
The app geocodes the location, searches public business data, enriches it from public websites, and writes the formatted output to `details.txt`.

### 2. Review Generated Leads

Generated results are shown in a frontend table.  
You can search within the generated results using the live search bar and suggestions.

### 3. Upload to Database

Click `Upload to Database` to store leads in MongoDB.

Duplicate detection is handled using a `dedupe_key`, so existing business records are skipped automatically.

### 4. Browse Saved Leads

Use the `All Leads` page to view already stored leads and filter them by location-based fields.

## MongoDB Configuration

- MongoDB URI: `mongodb://localhost:27017`
- Database name: `leadgen_DB`
- Collection name: `business_leads`

## Installation

### 1. Open the project folder

```powershell
cd "C:\Users\muham\Desktop\leadgen-tool"
```

### 2. Install dependencies

```powershell
& "C:\Users\muham\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m pip install -r requirements.txt
```

### 3. Make sure MongoDB is running locally

Default connection used by the app:

```text
mongodb://localhost:27017
```

## Run the Web App

```powershell
cd "C:\Users\muham\Desktop\leadgen-tool"
& "C:\Users\muham\AppData\Local\Python\pythoncore-3.14-64\python.exe" app.py
```

Open in your browser:

```text
http://127.0.0.1:5000
```

## Pages

### Home

```text
http://127.0.0.1:5000/
```

Use this page to:

- Generate leads
- Review generated data
- Search generated data live
- Upload new leads to MongoDB

### All Leads

```text
http://127.0.0.1:5000/alleads
```

Use this page to:

- View existing database leads
- Filter by country
- Filter by state / province
- Filter by district / neighborhood
- Filter by city
- Filter by location text

## Run the CLI Version

You can also generate `details.txt` directly from the terminal.

```powershell
cd "C:\Users\muham\Desktop\leadgen-tool"
& "C:\Users\muham\AppData\Local\Python\pythoncore-3.14-64\python.exe" .\collect_miami_business_details.py --country "United States" --state "Florida" --city "Miami" --limit 5 --output details.txt
```

Example with district:

```powershell
& "C:\Users\muham\AppData\Local\Python\pythoncore-3.14-64\python.exe" .\collect_miami_business_details.py --country "United States" --state "Florida" --city "Miami" --district "Brickell" --limit 5 --output details.txt
```

## API Endpoints

### `POST /api/search`

Searches public business leads for the given structured location.

Example payload:

```json
{
  "country": "United States",
  "state": "Florida",
  "district": "Brickell",
  "city": "Miami",
  "limit": 5
}
```

### `POST /api/upload`

Uploads generated leads into MongoDB and skips duplicates.

### `GET /api/alleads`

Returns saved leads from MongoDB with optional filters.

Example:

```text
/api/alleads?country=United%20States&state=Florida&city=Miami
```

## Output File

Generated lead output is written to:

```text
details.txt
```

Each lead is formatted like:

```text
Business Name: ...
Location: ...
Phone: ...
Email: ...
Website: ...
Social Media:
- Facebook: ...
- Instagram: ...
- LinkedIn: ...
- X/Twitter: ...
- YouTube: ...
----------------------------------------
```

## Notes

- Search quality depends on publicly available data in the selected location.
- Some locations may return fewer results than others.
- Older MongoDB records may have less structured location metadata than newer uploads.
- New uploads store better structured location data for improved filtering.

## Future Improvements

Possible next upgrades:

- Pagination for generated leads and saved leads
- Sorting controls
- Export to CSV
- Edit and delete saved leads
- Cascading location dropdowns
- Category or industry filters

## License

This project is currently for local/private use unless you choose to add a license.
