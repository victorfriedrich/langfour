import os
from fastapi import FastAPI, Query, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pydantic import conint, confloat
from typing import List, Dict, Optional
from types import SimpleNamespace
import json
from videoparsing import main as process_video
from text_article_parsing import parse_article
from recommender import Recommender
import logging
from dotenv import load_dotenv
from supabase import create_client, Client
from auth import AuthMiddleware, get_current_user, security
from database import (
    initialize_cache
)
from nlp_processing import get_missing_words, parse_and_translate_word, translate_section, generate_word_examples
from utils import get_video_words
from languages import require_code
import asyncio
from fastapi import Query, Body
from file_manager import get_categories_with_icons, language_categories_cache, initialize_categories
from flashcards import router as flashcards_router
from media_import import get_media, import_media, list_media
from nlp_processing import group_text, parse
import asyncio


app = FastAPI()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Middleware.
#
# Order matters: Starlette runs the LAST-added middleware outermost. CORS is
# added last so that 401 responses from AuthMiddleware still carry CORS
# headers -- otherwise the browser reports an opaque CORS failure instead of
# the actual 401 and the real cause is invisible in the console.
# ---------------------------------------------------------------------------
app.add_middleware(AuthMiddleware)

# allow_origins=["*"] together with allow_credentials=True is invalid per the
# CORS spec -- browsers reject a wildcard origin on credentialed requests, so
# the previous config was not doing what it appeared to. Origins are now
# explicit and configured per environment.
_default_origins = "http://localhost:3000,https://langfive.com,https://www.langfive.com"
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()
]

# The Chrome extension calls this API from content scripts, which send an
# Origin of chrome-extension://<id>. Set EXTENSION_ID in the environment.
_extension_id = os.getenv("EXTENSION_ID", "").strip()
if _extension_id:
    ALLOWED_ORIGINS.append(f"chrome-extension://{_extension_id}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Include the flashcards endpoints with a prefix.
app.include_router(flashcards_router, prefix="/flashcards", tags=["flashcards"])

# Client now comes from supabase_client, which verifies the key is
# service_role before the app is allowed to start.
from supabase_client import supabase, SUPABASE_URL as supabase_url



from paths import PROCESSED_DIR
from corpus_sync import ensure_corpus
VIDEO_DIR = str(PROCESSED_DIR)

class ExampleRequest(BaseModel):
    words: List[str] = Field(..., description="Array of words / phrases")
    language: str   = Field("es", description="Target language (e.g. 'es', 'en')")

class ExampleEntry(BaseModel):
    sentences:  List[str] = Field(..., min_items=2, max_items=2)
    highlights: List[str] = Field(..., min_items=2, max_items=2)

class TextRequest(BaseModel):
    text: str
    language: str
    
class VideoRequest(BaseModel):
    url: str
    language: str

class TranscriptChunk(BaseModel):
    timestamp: List[float] = Field(..., min_length=2, max_length=2)
    text: str = Field(..., min_length=1)

class MediaImportRequest(BaseModel):
    series: str = Field(..., min_length=1)
    language: str = Field(..., description="Language name or ISO code")
    chunks: List[TranscriptChunk] = Field(..., min_length=1)
    title: Optional[str] = None
    season: Optional[conint(ge=0)] = None
    episode: Optional[conint(ge=0)] = None
    media_id: Optional[str] = None
    media_type: str = "series"
    model: Optional[str] = None
    timebase: Optional[str] = None
    audio_seconds: Optional[confloat(gt=0)] = None

class RankBlendedVideoResponse(BaseModel):
    ids:          List[str]
    titles:       List[str]
    scores:       List[float]
    ratios:       List[float]  # fraction of words understood (0.0–1.0)
    newWords:     List[int]    # count of truly new words (user doesn’t know)
    usefulWords:  List[int]    # count of prioritized words present

class VideoRecommendation(BaseModel):
    id: str
    percentUnderstood: int

class VideoRecommendationResponse(BaseModel):
    ids: List[str]
    titles: List[str]
    ratios: List[float]
    newWords: List[int]
    
class WordRecommendationResponse(BaseModel):
    word_ids: List[int]
    improvements: List[float]
    frequencies: List[int]

class MissingWordsRequest(BaseModel):
    language_code: str
    
class ChartDataResponse(BaseModel):
    n_values: List[int]  # List of n values
    ordered_by_id: List[float]  # Percent understood corresponding to each n
    random_selection: List[float]  # Percent understood corresponding to each n
    category_top: List[float]  # Percent understood corresponding to each n (if category is provided)

class VocabCoverageResponse(BaseModel):
    top30_avg: float
    bottom30_avg: float
    
# get_current_user and the bearer scheme now live in auth.py. Every request is
# already verified by AuthMiddleware before it reaches a handler, so the
# dependency just reads request.state.user -- no second network call to GoTrue.

@app.on_event("startup")
async def startup_event():
    load_dotenv()

    # Must run before the recommenders are built: they read the transcript
    # corpus off disk, and in a container that disk starts empty. No-op when
    # the corpus is already present (local dev) or no source is configured.
    ensure_corpus()

    initialize_cache()
    initialize_categories()

    # now instantiate here, so import-time is fast
    app.state.recommender         = Recommender(base_folder=VIDEO_DIR)

@app.post("/parse")
async def parse_text(request: TextRequest):
    print(request.text)
    title, parsed_content = parse_article(request.text, request.language.lower())

    return {
        "title": title,
        "parsed_json": parsed_content
    }

@app.get("/")
def health_check():
    print("/health_check received!")
    return {"status": "ok"}


@app.get("/recommendations/words/", response_model=WordRecommendationResponse)
async def get_word_recommendations(
    request: Request,
    current_user: dict = Depends(get_current_user),
    category: str = Query(None, description="Category to search"),
    language: str = Query("es", description="Language Country Code"),
    n_words: int = Query(100, description="Number of words to recommend"),
):
    recommender = request.app.state.recommender
    if (not language.isalnum()) or len(language) > 2:
        return
        
    # Get user's known words
    known_words = await recommender.get_known_words(current_user.id)
        
    # Get word recommendations
    recommendations = recommender.recommend_words_to_learn(
        language=language,
        known_word_ids=known_words,
        filter_category=category if category else None,
        n_words=n_words
    )
    
    # Extract data for response
    word_ids = [rec["word_id"] for rec in recommendations]
    improvements = [rec["improvement"] for rec in recommendations]
    frequencies = [rec["frequency"] for rec in recommendations]
    
    return WordRecommendationResponse(
        word_ids=word_ids,
        improvements=improvements,
        frequencies=frequencies
    )

@app.get(
    "/recommendations/videos/custom",
    response_model=RankBlendedVideoResponse,
    summary="Blend ranking positions + include unique prioritized-word counts and understood ratios",
)
async def get_rank_blended_recommendations(
    request: Request,
    tradeoff:       confloat(ge=0.0, le=1.0) = Query(
                       0.5, description="λ for known-rank vs useful-rank"
                   ),
    video_category: str        = Query(None, description="Filter videos by this category"),
    word_category:  str        = Query(None, description="Which new-word category to pull"),
    language:       str        = Query("es", description="Language Country Code"),
    top_n:          conint(gt=0) = Query(100, description="Candidates per list"),
    current_user:   dict       = Depends(get_current_user),
):
    recommender = request.app.state.recommender
    # 1) Traditional recs & their unknown-word counts + understood ratios
    known_videos = await recommender.recommend_videos(
        user_id=current_user.id,
        language=language,
        filter_category=video_category,
        top_n=top_n,
    )
    max_known = len(known_videos)
    known_rank_map = {
        v["id"]: (max_known - idx + 1) / max_known
        for idx, v in enumerate(known_videos, start=1)
    }
    known_new_map   = {v["id"]: v.get("newWords", 0) for v in known_videos}
    known_ratio_map = {
        v["id"]: v.get("percentUnderstood", 0.0) / 100.0
        for v in known_videos
    }

    # 2) New-word recs & their presence counts + fallback ratios
    known_ids = await recommender.get_known_words(current_user.id)
    new_word_list = recommender.recommend_words_to_learn(
        language=language,
        known_word_ids=known_ids,
        filter_category=word_category,
        n_words=200,
    )
    print("New word list:")
    print(new_word_list)
    new_ids = [w["word_id"] for w in new_word_list]

    print("New IDs")
    print(new_ids)
    
    useful_videos = recommender.recommend_videos_by_words(
        word_ids=new_ids,
        language=language,
        filter_category=video_category,
        top_n=top_n,
    )
    max_useful = len(useful_videos)
    useful_rank_map = {
        v["id"]: (max_useful - idx + 1) / max_useful
        for idx, v in enumerate(useful_videos, start=1)
    }

    # **Just reuse the deduped newWords count from your recommender**
    useful_new_map = {
        v["id"]: v.get("knownWords", 0)
        for v in useful_videos
    }
    useful_ratio_map = {
        v["id"]: v.get("percentUnderstood", 0.0) / 100.0
        for v in useful_videos
    }

    # 3) Merge & compute blended score + pick ratio from known if available, else useful
    all_ids = set(known_rank_map) | set(useful_rank_map)
    scored = []
    for vid in all_ids:
        kr = known_rank_map.get(vid, 0.0)
        ur = useful_rank_map.get(vid, 0.0)
        blended_score = tradeoff * kr + (1 - tradeoff) * ur

        title = next(
            (v["title"] for v in known_videos if v["id"] == vid),
            next((v["title"] for v in useful_videos if v["id"] == vid), ""),
        )
        ratio = known_ratio_map.get(vid, useful_ratio_map.get(vid, 0.0))

        scored.append((
            blended_score,
            vid,
            title,
            ratio,
            known_new_map.get(vid, 0),
            useful_new_map.get(vid, 0),
        ))

    # 4) Sort & unpack
    scored.sort(key=lambda x: x[0], reverse=True)
    scores, ids, titles, ratios, newWords, usefulWords = map(list, zip(*scored))

    return RankBlendedVideoResponse(
        ids=ids,
        titles=titles,
        scores=scores,
        ratios=ratios,
        newWords=newWords,
        usefulWords=usefulWords
    )
    
@app.get("/recommendations/videos/", response_model=VideoRecommendationResponse)
async def get_video_recommendations(
    request: Request,
    include_cognates: bool = Query(False, description="Include cognates in recommendations"),
    category: str = Query(None, description="Category for recommendations"),
    language: str = Query("es", description="Language Country Code"),
    current_user: dict = Depends(get_current_user)
):
    recommender = request.app.state.recommender
    if (not language.isalnum()) or len(language) > 2:
        return
    
    print("Request starting")
    
    videos = await recommender.recommend_videos(
        user_id=current_user.id,
        language=language,
        filter_category=category,
        top_n=100
    )
    titles = [video["title"] for video in videos]
    video_ids = [video["id"] for video in videos]
    ratios = [video["percentUnderstood"] / 100 for video in videos]
    new_words = [video["newWords"] for video in videos]
    
    return VideoRecommendationResponse(ids=video_ids, ratios=ratios, newWords=new_words, titles=titles)

@app.post("/api/videos/{video_id}/missing-words")
async def check_missing_words(
    video_id: str, 
    request: MissingWordsRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        # get_video_words reads the ISO-named transcript directory; get_missing_words
        # queries words.language. Both take the same key now, so the mapping that
        # used to sit between them -- and which never handled 'fr' -- is gone.
        language_code = require_code(request.language_code)

        words = get_video_words(video_id, language_code)

        missing_words = await get_missing_words(current_user.id, words, language_code)
        
        return {"missing_words": missing_words}
    except Exception as e:
        logger.exception("💥 unhandled error in /missing-words")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/categories")
async def get_categories():
    try:
        categories = get_categories_with_icons(str(PROCESSED_DIR / "de"))
        return {"categories": categories}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching categories: {str(e)}")

@app.get("/categories/videos")
async def get_video_categories(language: str = Query("es", description="Language Country Code")):
    if (not language.isalnum()) or len(language) > 2:
        raise HTTPException(status_code=400, detail="Invalid language code")
    
    if language not in language_categories_cache:
        raise HTTPException(status_code=404, detail="Language not supported")
    
    return {"categories": language_categories_cache[language]}

@app.get("/api/videos/{video_id}")
async def get_video_info(video_id: str):
    try:
        words = get_video_words(video_id)
        return {"video_id": video_id, "words": words}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/translate-word")
async def translate_word(word: str = Body(...), language: str = Body(...)):
    try:
        result = parse_and_translate_word(word, language)
        return result
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error translating word: {str(e)}")

# Language is the ISO code, e.g. 'es'. require_code() also accepts the legacy
# long name, so older callers keep working.
@app.post("/api/translate")
async def translate(section: str = Body(...), language: str = Body(...)):
    try:
        result = translate_section(section, language)
        return result
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error translating section: {str(e)}")

@app.post("/api/process-video")
async def process_video_endpoint(request: VideoRequest):
    try:
        # Run the video processing in a separate thread to avoid blocking
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, process_video, request.url, request.language)
        
        # Extract video_id from the URL
        video_id = request.url.split('v=')[-1]
        
        return {"message": f"Video processing started for ID: {video_id}", "video_id": video_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing video: {str(e)}")

@app.post("/api/media/import", status_code=201)
async def import_media_endpoint(request: MediaImportRequest):
    """Import a timestamped transcript as an episode or other media item."""
    try:
        payload = request.model_dump()
        return await asyncio.to_thread(import_media, payload, parse, group_text)
    except FileExistsError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:
        logger.exception("Failed to import media transcript")
        raise HTTPException(status_code=500, detail=f"Failed to import media: {error}")

@app.get("/api/media")
async def get_imported_media(
    language: str = Query("es", description="Language name or ISO code"),
):
    """Return lightweight metadata for the frontend's imported-media tab."""
    try:
        return {"media": list_media(language)}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

@app.get("/api/media/{media_id}")
async def get_imported_media_item(
    media_id: str,
    language: str = Query("es", description="Language name or ISO code"),
):
    """Return metadata and timestamped chunks for one imported item."""
    try:
        return {"media": get_media(media_id, language)}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Media not found: {media_id}")
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.get("/recommendations/words/chart-data", response_model=ChartDataResponse)
async def get_chart_data(
    request: Request,
    language: str = Query("es", description="Language Country Code"),
    category: str = Query(None, description="Category to filter (optional)"),
    max_n: int = Query(1000, description="Maximum number of words to include"),
    step: int = Query(100, description="Step size for n values"),
):
    recommender = request.app.state.recommender
    """
    Generate data for line chart visualizing average percent understood across different word selections.
    Assumes the user knows no words (known_word_ids is empty).
    """
    try:
        # Validate parameters
        if max_n <= 0 or step <= 0:
            raise HTTPException(status_code=400, detail="max_n and step must be positive integers")
        if step > max_n:
            raise HTTPException(status_code=400, detail="step cannot be greater than max_n")

        # Define the range of n values
        n_values = list(range(step, max_n + 1, step))

        # Normalised into `language` itself rather than a second `db_language`
        # name: the recommender calls below were still reading the raw
        # parameter, so one function held both vocabularies at once and every
        # new line in it was a coin flip on which to use.
        language = require_code(language)

        # Pre-fetch ordered words once using a more robust query
        ordered_query = (
            supabase.table("languagelevels")
            .select("word_id")
            .eq("language", language)
            .eq("language_level", "B2")
            .order("id")
            .limit(max_n)
            .execute()
        )
        ordered_word_ids_all = [row.get("word_id") for row in ordered_query.data]

        # Pre-fetch random words once
        random_words_all = recommender.get_random_words(language, limit=max_n)

        # Initialize lists to hold average percent understood for each selection method
        ordered_percent_understood = []
        random_percent_understood = []
        category_top_percent_understood = []

        # Since user knows no words, known_word_ids is empty
        known_word_ids = []

        for n in n_values:
            # 1. Ordered by ID
            ordered_word_ids = ordered_word_ids_all[:n]
            ordered_recommendations = recommender.recommend_videos_by_words(
                word_ids=ordered_word_ids,
                language=language,
                filter_category=category,
                top_n=50,
            )
            if ordered_recommendations:
                avg_percent_ordered = sum(rec["percentUnderstood"] for rec in ordered_recommendations) / len(ordered_recommendations)
            else:
                avg_percent_ordered = 0.0
            ordered_percent_understood.append(avg_percent_ordered)

            # 2. Random Selection
            random_word_ids = random_words_all[:n]
            random_recommendations = recommender.recommend_videos_by_words(
                word_ids=random_word_ids,
                language=language,
                filter_category=category,
                top_n=50,
            )
            if random_recommendations:
                avg_percent_random = sum(rec["percentUnderstood"] for rec in random_recommendations) / len(random_recommendations)
            else:
                avg_percent_random = 0.0
            random_percent_understood.append(avg_percent_random)

            # 3. Category Top
            if category:
                # Get top n words in the category
                recommendations = recommender.recommend_words_to_learn(
                    language=language,
                    known_word_ids=known_word_ids,  # Empty list
                    filter_category=category,
                    n_words=n
                )
                category_word_ids = [rec["word_id"] for rec in recommendations]
                category_videos = recommender.recommend_videos_by_words(
                    word_ids=category_word_ids,
                    language=language,
                    filter_category=category,
                    top_n=50
                )
                if category_videos:
                    avg_percent_category = sum(rec["percentUnderstood"] for rec in category_videos) / len(category_videos)
                else:
                    avg_percent_category = 0.0
                category_top_percent_understood.append(avg_percent_category)
            else:
                # If no category provided, append 0.0
                category_top_percent_understood.append(0.0)

        # Prepare the response
        response = ChartDataResponse(
            n_values=n_values,
            ordered_by_id=ordered_percent_understood,
            random_selection=random_percent_understood,
            category_top=category_top_percent_understood if category else []
        )

        return response

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Unexpected error in /recommendations/words/chart-data: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

@app.get("/vocabulary/{vocab_id}/coverage", response_model=VocabCoverageResponse)
async def vocabulary_coverage(
    vocab_id: str,
    request: Request,
    language: str = Query("es", description="Language Country Code"),
):
    """Calculate average percent understood for the top and bottom 30% of videos."""
    recommender = request.app.state.recommender

    # Fetch known words for the provided vocabulary/user ID
    known_words = await recommender.get_known_words(vocab_id)

    try:
        recommender._ensure_language_loaded(language)
    except ValueError:
        raise HTTPException(status_code=404, detail="Language not supported")
    matrix = recommender.matrices[language]

    # Evaluate comprehension for all available videos for this language
    all_videos = recommender.recommend_videos_by_words(
        word_ids=known_words,
        language=language,
        top_n=matrix.shape[0],
    )

    if not all_videos:
        return VocabCoverageResponse(top30_avg=0.0, bottom30_avg=0.0)

    count = max(1, int(len(all_videos) * 0.3))
    top_segment = all_videos[:count]
    bottom_segment = all_videos[-count:]

    def avg_percent(videos):
        return sum(v["percentUnderstood"] for v in videos) / len(videos) if videos else 0.0

    return VocabCoverageResponse(
        top30_avg=avg_percent(top_segment),
        bottom30_avg=avg_percent(bottom_segment),
    )

# @app.on_event("startup")
# async def startup_event():
    
@app.post(
    "/api/example-sentences",
    response_model=Dict[str, ExampleEntry],
    summary="Generate A1–A2 example sentences for each supplied word",
    tags=["nlp"],
)
async def example_sentences_endpoint(
    payload: ExampleRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Returns JSON like:
    {
      "apple": {
        "sentences":  ["I eat an apple.", "The apples are juicy."],
        "highlights": ["apple", "apples"]
      },
      ...
    }
    """
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,                     # default ThreadPoolExecutor
            generate_word_examples,
            payload.words,
            payload.language,         # ← pass language
        )
        return result
    except Exception as e:
        logger.exception("💥 Error generating example sentences")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
