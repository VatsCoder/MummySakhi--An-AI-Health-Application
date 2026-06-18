# MummySakhi — AI-Powered Health Monitoring System

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python)
![Flask](https://img.shields.io/badge/Flask-3.x-black?style=flat-square&logo=flask)
![Gemini](https://img.shields.io/badge/Gemini-2.0%20Flash-orange?style=flat-square&logo=google)
![SQLite](https://img.shields.io/badge/SQLite-3-lightblue?style=flat-square&logo=sqlite)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)

---

## Overview

**MummySakhi** is a web-based health monitoring platform designed to assist expecting mothers in tracking their day-to-day health metrics, logging symptoms, and receiving AI-generated clinical insights from their uploaded medical reports.

The system leverages **Google Gemini 2.0 Flash** for intelligent biomarker extraction and health analysis, **pdfplumber** and **Tesseract OCR** for local document processing, and a lightweight **SQLite** database for persistent user data storage — all served through a **Flask** backend.

The application was developed with accessibility, privacy, and clinical relevance in mind, aiming to bridge the gap between raw medical data and actionable guidance for mothers during pregnancy or mothers of any age.

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Environment Variables](#environment-variables)
  - [Running the Application](#running-the-application)
- [Database Schema](#database-schema)
- [AI Pipeline](#ai-pipeline)
- [Deployment](#deployment)
- [Known Limitations](#known-limitations)
- [Future Roadmap](#future-roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## Features

- **User Authentication** — Secure registration and login with optional persistent sessions (30-day remember me).
- **Health Profile Management** — Users can save and update personal health details including age, height, weight, and pre-existing conditions.
- **Daily Health Logging** — Track sleep hours, workload, exercise duration, and daily symptoms through a structured check-in form.
- **BMI Calculation** — Automatic Body Mass Index calculation with status classification (Underweight, Healthy, Overweight, Obese).
- **Sleep Quality Tracking** — Weekly average sleep analysis with percentage comparison against the previous week.
- **Medical Report Upload** — Accepts PDF and image-based medical reports (blood tests, lab panels, ultrasounds).
- **AI-Powered Report Analysis** — Automated biomarker extraction and clinical insight generation using Google Gemini 2.0 Flash, executed in a background thread to prevent request timeouts.
- **Historical Trend Comparison** — Gatekeeper logic determines whether historical biomarker data is relevant and feeds it into the final AI analysis.
- **Risk Level Assessment** — Dynamic risk classification (Low / Medium / High) derived from BMI, sleep quality, and abnormal marker count.
- **Real-Time Processing Status** — Dashboard auto-refreshes every 8 seconds while a report is being processed, displaying appropriate loading and error states.
- **Secure Configuration** — All sensitive credentials managed through environment variables using `python-dotenv`.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend Framework | Flask 3.x |
| Database | SQLite 3 (via `sqlite3`) |
| AI / LLM | Google Gemini 2.0 Flash (`google-genai`) |
| PDF Text Extraction | pdfplumber |
| OCR Engine | Tesseract OCR + pytesseract |
| Image Processing | Pillow (PIL) |
| Background Processing | Python `threading.Thread` |
| Environment Management | python-dotenv |
| Production Server | Gunicorn |
| Frontend | HTML5, CSS3, Jinja2 Templates |

---

## Project Structure

```
healthmemory/
│
├── app.py                  # Main Flask application — routes, logic, AI pipeline
├── database.db             # SQLite database (auto-generated on first run)
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables (never committed to version control)
├── .gitignore              # Excludes .env, database, uploads
├── nixpacks.toml           # Server build config for Railway deployment
│
├── static/
│   ├── css/
│   │   └── dashboard.css   # Dashboard stylesheet
│   └── uploads/            # Uploaded medical reports (auto-created)
│
└── templates/
    ├── index.html           # Landing page
    ├── get_started.html     # Onboarding page
    ├── login.html           # Login page
    ├── profile.html         # Profile setup and editing
    └── dashboard.html       # Main dashboard interface
```

---

## Getting Started

### Prerequisites

Ensure the following are installed on your system before proceeding.

**Python 3.10 or higher**
```bash
python --version
```

**Tesseract OCR Engine**

On Ubuntu / Debian:
```bash
sudo apt update && sudo apt install tesseract-ocr -y
```

On macOS:
```bash
brew install tesseract
```

On Windows — download the installer from:
```
https://github.com/UB-Mannheim/tesseract/wiki
```

Verify the installation:
```bash
tesseract --version
```

---

### Installation

**1. Clone the repository**
```bash
git clone https://github.com/your-username/healthmemory.git
cd healthmemory
```

**2. Create and activate a virtual environment**
```bash
python -m venv venv

# Linux / macOS
source venv/bin/activate

# Windows
venv\Scripts\activate
```

**3. Install Python dependencies**
```bash
pip install -r requirements.txt
```

---

### Environment Variables

Create a `.env` file in the project root directory:

```bash
touch .env
```

Add the following variables:

```env
SECRET_KEY=your_generated_secret_key_here
GEMINI_API_KEY=your_google_gemini_api_key_here
```

To generate a secure secret key, run:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

To obtain a Gemini API key, visit:
```
https://aistudio.google.com/app/apikey
```

> **Important:** Never commit the `.env` file to version control. Ensure `.env` is listed in your `.gitignore`.

---

### Running the Application

**Development mode:**
```bash
python app.py
```

The application will be available at `http://localhost:5000`.

**Production mode (Gunicorn):**
```bash
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

---

## Database Schema

The application initialises the following tables automatically on first run.

### `users`
| Column | Type | Description |
|---|---|---|
| id | INTEGER PK | Auto-incremented user identifier |
| name | TEXT | Full name of the user |
| email | TEXT UNIQUE | User email address |
| password | TEXT | User password |

### `profile`
| Column | Type | Description |
|---|---|---|
| id | INTEGER PK | Auto-incremented profile identifier |
| user_id | INTEGER FK | References `users.id` |
| age | INTEGER | User age in years |
| height | INTEGER | Height in centimetres |
| weight | INTEGER | Weight in kilograms |
| condn | TEXT | Pre-existing medical conditions |

### `daily_logs`
| Column | Type | Description |
|---|---|---|
| id | INTEGER PK | Auto-incremented log identifier |
| user_id | INTEGER FK | References `users.id` |
| sleep_hours | REAL | Hours of sleep logged |
| workload_hours | REAL | Hours of work logged |
| exercise_mins | INTEGER | Minutes of exercise |
| symptoms | TEXT | Comma-separated symptom list |
| log_date | DATE | Date of the log entry |

### `medical_reports`
| Column | Type | Description |
|---|---|---|
| id | INTEGER PK | Auto-incremented report identifier |
| user_id | INTEGER FK | References `users.id` |
| file_path | TEXT | Server path to uploaded file |
| ai_analysis | TEXT | Final AI-generated insight text |
| upload_date | DATE | Date of upload |
| status | TEXT | `processing`, `done`, or `failed` |

### `report_values`
| Column | Type | Description |
|---|---|---|
| id | INTEGER PK | Auto-incremented row identifier |
| report_id | INTEGER FK | References `medical_reports.id` |
| marker | TEXT | Biomarker name (e.g. Hemoglobin) |
| value | TEXT | Measured value (e.g. 11.2 g/dL) |
| reference | TEXT | Normal reference range |
| status | TEXT | `Normal`, `Low`, or `High` |

---

## AI Pipeline

The AI analysis pipeline runs entirely in a **background thread** to prevent HTTP request timeouts. The following steps are executed after a report is uploaded:

```
User uploads PDF or image
        │
        ▼
Text extracted locally
(pdfplumber → pytesseract fallback)
        │
        ▼
DB record created with status = 'processing'
        │
        ▼
User redirected to dashboard instantly
        │
        ▼  [Background Thread]
Step 1: Gemini extracts biomarkers → structured JSON
        │
        ▼
Step 2: Biomarkers saved to report_values table
        │
        ▼
Step 3: Gatekeeper decides if historical data is needed
        │
        ▼
Step 4: Final insight generation with optional history
        │
        ▼
Step 5: ai_analysis saved, status set to 'done'
        │
        ▼
Dashboard auto-refreshes and displays results
```

**Retry logic:** All Gemini API calls include exponential backoff retry (up to 5 attempts, starting at 5 seconds, tripling each attempt) to handle temporary 503 service unavailability errors gracefully.

---

## Deployment

### Railway (Recommended)

**1.** Push your project to a GitHub repository.

**2.** Create a `nixpacks.toml` in the project root to install Tesseract on the server:

```toml
[phases.setup]
aptPkgs = ["tesseract-ocr"]
```

**3.** Connect the GitHub repository to a new Railway project.

**4.** Set environment variables in the Railway dashboard under **Variables**:
```
SECRET_KEY=your_secret_key
GEMINI_API_KEY=your_gemini_key
```

**5.** Railway will automatically detect the Python project, install dependencies from `requirements.txt`, and deploy.

### Ubuntu VPS (Manual)

```bash
# Install system dependencies
sudo apt update
sudo apt install python3-pip tesseract-ocr -y

# Install Python packages
pip install -r requirements.txt

# Set environment variables
export SECRET_KEY="your_secret_key"
export GEMINI_API_KEY="your_gemini_key"

# Run with Gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

For persistent deployment with auto-restart, configure a `systemd` service unit pointing to the Gunicorn start command.

---

## Known Limitations

- **Password Storage** — Passwords are currently stored in plain text. A production deployment should implement hashing using `bcrypt` or `werkzeug.security`.
- **File Storage** — Uploaded reports are stored on the local filesystem. A cloud storage solution (AWS S3, Cloudflare R2) is recommended for scalable deployments.
- **OCR Accuracy** — Handwritten or low-resolution scanned reports may yield incomplete text extraction, affecting biomarker identification accuracy.
- **Gemini Free Tier** — The free tier of Gemini 2.0 Flash is limited to 1,500 requests per day. High-traffic usage will require a paid API plan.
- **Single-user Threading** — The current background thread model is suitable for low-concurrency usage. A task queue (Celery + Redis) is recommended for production scale.

---

## Future Roadmap

- [ ] Password hashing and secure authentication
- [ ] Cloud file storage integration (AWS S3 / Cloudflare R2)
- [ ] Trimester-specific health recommendations
- [ ] Multi-language support (Hindi, regional Indian languages)
- [ ] Push notifications for critical biomarker alerts
- [ ] Doctor / healthcare provider sharing portal
- [ ] Mobile-responsive PWA (Progressive Web App)
- [ ] Celery + Redis task queue for production-grade background processing
- [ ] Export health summary as PDF report

---

## Contributing

Contributions are welcome. To contribute:

1. Fork the repository
2. Create a new branch (`git checkout -b feature/your-feature-name`)
3. Commit your changes (`git commit -m 'Add: your feature description'`)
4. Push to the branch (`git push origin feature/your-feature-name`)
5. Open a Pull Request

Please ensure your code follows the existing structure and includes appropriate comments.

---

## License

This project is licensed under the **MIT License**. You are free to use, modify, and distribute this software in accordance with the terms of the license.

---

> Developed with the goal of making maternal healthcare more accessible, informed, and proactive.
