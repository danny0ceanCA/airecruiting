# Air Recruiting Full-Stack App

This repository contains a basic full-stack application with a FastAPI backend and a React frontend.

## Backend

The backend uses [FastAPI](https://fastapi.tiangolo.com/). The entry point is `app/main.py`.
Run it with:

```bash
uvicorn app.main:app --reload
```

## Frontend

The frontend was bootstrapped with Create React App and lives in the `frontend` folder. Install dependencies and start the development server with:

```bash
cd frontend
npm install
npm start
```

## Tests

Tests use `pytest`. Run them with:

```bash
pytest
```
