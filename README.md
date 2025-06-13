# Air Recruiting Full-Stack App

This repository contains a basic full-stack application with a FastAPI backend and a React frontend.

## Backend

The backend uses [FastAPI](https://fastapi.tiangolo.com/). The entry point is `app/main.py`.
Run it with:

```bash
uvicorn app.main:app --reload
```

## Frontend

The frontend is a minimal React application located in the `frontend` folder. Open `frontend/index.html` in a browser to see the app.

## Tests

Tests use `pytest`. Run them with:

```bash
pytest
```
