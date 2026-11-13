import io
import logging
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile

from src import HealthResponse, setup_logging, ProcessConfig
from data_pipeline import create_cleaning_report, process_data, validate_dataframe
from src import (
    MovieStorage,
    MovieUploadInfo,
    MovieDataResponse,
    MovieProcessingReport,
)
from src.storage import MOVIE_COLUMNS


setup_logging(verbose=True)
logger = logging.getLogger(__name__)

app = FastAPI(title="Data Processing API", version="1.0.0")
storage = MovieStorage()


@app.get("/health", response_model=HealthResponse)
def health_check():
    """Return the application status and version."""
    return HealthResponse(status="ok", version=app.version)


@app.post("/upload", response_model=MovieUploadInfo)
async def upload_movies(file: UploadFile = File(...)):
    """Read a CSV upload and replace the stored movie collection."""
    # TODO 1: .csv check, read, and parse (kept from MP2)
    filename = file.filename or ""
    if Path(filename).suffix.lower() != ".csv":
        logger.warning(f"Rejected upload with unsupported file type: {filename!r}")
        raise HTTPException(status_code=400, detail="Only .csv files are accepted")

    contents = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(contents))
    except pd.errors.EmptyDataError:
        logger.warning(f"Upload {filename} is empty")
        raise HTTPException(status_code=400, detail="The uploaded CSV file is empty")
    except pd.errors.ParserError as e:
        logger.warning(f"Could not parse {filename}: {e}")
        raise HTTPException(status_code=400, detail="The file could not be parsed as CSV; check its formatting")
    except UnicodeDecodeError as e:
        logger.warning(f"Encoding error in {filename}: {e}")
        raise HTTPException(status_code=400, detail="The file's text encoding is unsupported; please save it as UTF-8")

    # TODO 2: quick validation
    if set(df.columns) != set(MOVIE_COLUMNS) or len(df.columns) != len(MOVIE_COLUMNS):
        logger.warning(f"Upload {filename} has invalid columns: {list(df.columns)}")
        raise HTTPException(
            status_code=400,
            detail=f"CSV must have exactly these columns: {MOVIE_COLUMNS}",
        )

    if df.empty:
        logger.warning(f"Upload {filename} has no data rows")
        raise HTTPException(status_code=400, detail="The uploaded CSV has no data rows")

    df = df[MOVIE_COLUMNS]

    # TODO 3: save and return
    storage.save(df)
    logger.info(f"Stored {len(df)} movies from {filename}")

    return MovieUploadInfo(
        filename=filename,
        rows=len(df),
        columns=len(df.columns),
        column_names=list(df.columns),
    )


@app.get("/movies", response_model=MovieDataResponse)
def get_movies(limit: int = Query(default=100, ge=1)):
    """Return up to limit stored movies and the total count."""
    total_rows = storage.count_movies()
    if total_rows == 0:
        logger.info("No movies stored; returning empty result")
        return {"data": [], "total_rows": 0}

    data = storage.select_columns(MOVIE_COLUMNS, limit=limit)
    logger.info(f"Returning {len(data)} of {total_rows} movies")

    return {"data": data, "total_rows": total_rows}


@app.get("/movies/search", response_model=list[dict])
def query_movies(
    columns: list[str] = Query(default=["title"]),
    min_rating: float = Query(default=0, ge=0, le=10),
    limit: int = Query(default=100, ge=1),
):
    """Return selected fields from movies at or above min_rating."""
    try:
        results = storage.query_movies(columns, min_rating, limit)
    except ValueError as error:
        logger.warning(f"Invalid search request: {error}")
        raise HTTPException(status_code=400, detail=str(error))

    logger.info(f"Search with columns {columns} returned {len(results)} movies")
    return results


@app.post("/movies/process", response_model=MovieProcessingReport)
def process_movies(config: ProcessConfig):
    """Validate and process the stored movies using MP1 functions."""
    # TODO 1: retrieve and check for empty
    df = storage.get()
    if df.empty:
        logger.warning("No movies stored to process")
        raise HTTPException(status_code=400, detail="No movies to process; upload a CSV first")
    df = df.copy()

    # TODO 2: reuse MP2's config, validation, processing, and report
    config_dict = config.model_dump()
    required_columns = config_dict["validation"]["required_columns"]
    numeric_columns = config_dict["validation"]["numeric_columns"]

    missing = [col for col in numeric_columns if col not in df.columns]
    if missing:
        logger.warning(f"Movies are missing numeric columns: {missing}")
        raise HTTPException(status_code=400, detail=f"Numeric columns not found in movies: {missing}")

    logger.info(f"Processing {len(df)} movies")

    try:
        validated_df = validate_dataframe(df, required_columns, numeric_columns)

        rows_removed_by_validation = len(df) - len(validated_df)
        logger.info(f"Validation removed {rows_removed_by_validation} rows")
        validated_copy = validated_df.copy()

        processed_df = process_data(validated_df, config_dict)
        logger.info(f"Processing produced {len(processed_df)} rows")

        report = create_cleaning_report(validated_copy, processed_df)

    except ValueError as error:
        logger.warning(f"Validation or processing failed: {error}")
        raise HTTPException(status_code=400, detail=str(error))

    # TODO 3: save and return (no dataset ID)
    storage.save(processed_df)
    logger.info("Stored processed movies")

    return {
        "validation_rows_removed": rows_removed_by_validation,
        "cleaning_report": report,
    }