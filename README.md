# Invoice Management App

A Streamlit app for managing invoices, powered by Snowflake.

## Setup (VS Code / Local Development)

### 1. Clone and install dependencies

```bash
git clone https://github.com/<your-username>/invoice-app.git
cd invoice-app
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e .
```

### 2. Configure Snowflake connection

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` with your Snowflake account details:

```
SNOWFLAKE_ACCOUNT=your_account_identifier
SNOWFLAKE_USER=your_username
SNOWFLAKE_PASSWORD=your_password
SNOWFLAKE_ROLE=ACCOUNTADMIN
SNOWFLAKE_WAREHOUSE=COMPUTE_WH
SNOWFLAKE_DATABASE=INVOICE_MGMT
SNOWFLAKE_SCHEMA=PUBLIC
```

### 3. Run the app

```bash
streamlit run streamlit_app.py
```

The app will open at `http://localhost:8501`.

## Features

- **Dashboard** - View invoice metrics and recent invoices
- **Create Invoice** - Add new invoices with customer details
- **Manage Invoices** - Update status or delete invoices

## Deployment

This app also runs natively in Snowsight (Snowflake's web UI) using `get_active_session()` — no credentials needed there.
