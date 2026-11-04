"""Start the development Uvicorn server with automatic reload enabled."""
import uvicorn


def main() -> None:
    """Run the FastAPI app on port 8000 for local development."""
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
