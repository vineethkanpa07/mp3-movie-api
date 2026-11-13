import pytest

from src import MovieStorage
import main

MOVIE_COLUMNS = ["title", "release_year", "rating", "genre"]

# Copy these from the test CSV your uploaded_movies fixture uses, in file order.
ORIGINAL_TITLES = [
    "Movie A",
    "Movie B",
    "Movie B",
    "Movie C",
    "Movie D",
    "Movie D",
    "Movie E",
    "Movie F",
    "Movie G",
    "Movie H",
    "Movie I",
    "Movie J",
    "Movie K",
    "Movie L",
    "Movie M",
    "Movie N",
    "Movie O",
    "Movie P",
    "Movie Q",
    "Movie R"
]


def test_movies_persist(client, test_storage, uploaded_movies):
    second_storage = MovieStorage(test_storage.db_path)

    df = second_storage.get()
    assert second_storage.count_movies() == 20
    assert len(df) == 20
    assert list(df.columns) == MOVIE_COLUMNS
    assert list(df["title"]) == ORIGINAL_TITLES

    storage_ids = [row["id"] for row in second_storage.select_columns(["title"], limit=100)]

    response = client.get("/movies", params={"limit": 100})
    assert response.status_code == 200
    api_ids = [row["id"] for row in response.json()["data"]]

    expected_ids = list(range(1, 21))
    assert storage_ids == expected_ids
    assert api_ids == expected_ids


def test_cache_and_processing(client, uploaded_movies, processing_body):
    # TODO 1: populate the cache for two limits
    response_100 = client.get("/movies", params={"limit": 100})
    assert response_100.status_code == 200
    assert main.cache.get(100) == response_100.json()

    response_1 = client.get("/movies", params={"limit": 1})
    assert response_1.status_code == 200
    assert main.cache.get(1) == response_1.json()

    # TODO 2: repeat limit=100
    repeat = client.get("/movies", params={"limit": 100})
    assert repeat.status_code == 200
    assert repeat.json() == response_100.json()

    # TODO 3: process and check the cache was cleared
    process = client.post("/movies/process", json=processing_body)
    assert process.status_code == 200
    body = process.json()
    assert body["validation_rows_removed"] == 0
    assert body["cleaning_report"]["rows_before"] == 20
    assert body["cleaning_report"]["rows_after"] == 16
    assert main.cache.get(100) is None
    assert main.cache.get(1) is None

    # TODO 4: retrieve the processed data
    after = client.get("/movies", params={"limit": 100})
    assert after.status_code == 200
    after_body = after.json()
    assert after_body["total_rows"] == 16

    expected_titles = [f"Movie {letter}" for letter in "ABCDEFGHIJKLMNOP"]
    assert [row["title"] for row in after_body["data"]] == expected_titles
    assert [row["id"] for row in after_body["data"]] == list(range(1, 17))
    assert main.cache.get(100) == after_body


def test_cache_hit_skips_database(client, uploaded_movies, monkeypatch):
    # TODO 1: populate the cache
    first = client.get("/movies", params={"limit": 100})
    assert first.status_code == 200