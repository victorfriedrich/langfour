import os
from nlp_processing import get_word_root, generate_alternatives, parse, group_text, filter_entities, get_tags
from database import save_to_supabase, identify_word_id, get_missing_words_from_db
from app import get_video_words, get_missing_words
from utils import is_special_character
from supabase import create_client, Client
import json
from fastapi import HTTPException
import pytest

# Set up environment variables or hard-code your test database connection parameters
from supabase_client import supabase, SUPABASE_URL, SUPABASE_KEY

# Create Supabase client

# Define test data
TEST_ROOT = "hacer"
ROOTS = ["haciendo"]
TEST_FORMS = [
    "hablo", "hablas", "habla", "hablamos", "habláis", "hablan",
    "hablaba", "hablabas", "hablábamos", "hablabais", "hablaban",
    "hablé", "hablaste", "habló", "hablamos", "hablasteis", "hablaron",
    "hablaré", "hablarás", "hablará", "hablaremos", "hablaréis", "hablarán",
    "hablaría", "hablarías", "hablaría", "hablaríamos", "hablaríais", "hablarían"
]

def test_get_word_root():
    print("Testing get_word_root...")
    for root in ROOTS:
        try:
            res = get_word_root(root)
            print(f"Root form of '{root}': {res}")
        except Exception as e:
            print(f"Error: {e}")

def test_generate_alternatives():
    
    testvalues = {
        "verb": ["hacer"],
        #"adjective": ["radical"],
        #
        #"noun": ["el nivel", "el ministro", "la seguridad"],
        #"other": ["sus", "en"]
    }
    
    for key in testvalues.keys():
        for value in testvalues[key]:
            #print(generate_alternatives(value, key))
            pass


def test_is_special_character():
    print("Testing is_special_character...")
    test_cases = [".", ",", "word", "!", "?", "'"]
    for char in test_cases:
        result = is_special_character(char)
        print(f"Is '{char}' a special character? {result}")

def test_group():
    input_text = "Málaga es luz, brillan su sol y sus casas blancas. Brilla el Meditarráneo mecido al ritmo de olas ondeantes y deslumbra también su historia. La de la Comarca de la Axarquía, al este de la provincia, dirige los focos hacia un pasado árabe."
    return group_text(input_text)

def test_parse():
    input_text = "Introducir la llave en el cerrojo del portón y encontrar a su primer morador supone abrirse a 9 kilómetros de playas."
    input_text = "El viajero encontrará su perfil rocoso durante el recorrido por el interior de la tierra. Dicen que los pozos situados cerca de la deidad regalan lo que ella otorgaba, fertilidad, por eso no falta quien moja los dedos en ese agua. 'Dicen' es una palabra muy repetida durante la visita audioguiada. Dicen que entre los 2 kilómetros de cueva (unos 600 metros visitables), se esconde un tesoro árabe buscado hasta perder el aliento (literalmente), por el suizo Antonio de la Nari, quien murió tras una de las voladuras explosionadas por él mismo a lo largo de 30 años."
    #input_text = "además de tomar el sol y nadar"
    groups = group_text(input_text)
    print(groups)
    
    result = parse(groups, "TEST")
    print(result)

def test_tags():
    get_tags("ME SUMERGI EN UN NAUFRAGIO! | ISLA LARGA - PUERTO CABELLO | intente hacer Snokel jeje", "Hello belleza bienvenidos sean todos a un nuevo vídeo de mi canal Mi nombre es Michelle y yo estoy muy contenta porque por fin ya salió el sol y estoy hoy haciéndoles este vídeo que tenía mucho tiempo queriendo hacerlos hoy vamos a hacer un block Playero hacer un día de playa con mimi Porque los voy a llevar a isla larga una de mis playas favoritas de acá de Puerto cabello es preciosa las fotos ahí son espectaculares y también el ambiente se disfruta muchísimo Yo estoy ahorita en la calle de los lanceros y ya salimos para acá en su corazón Ya llegamos acá a isla larga miren Qué precioso es el agua es Clarita me encanta porque hoy es viernes y hoy no hay casi gente la última vez que vine había muchísima gente y ustedes saben que así no se disfruta tanto pero hoy está solito miren eso qué lindo Además nos dejaron de este lado porque Generalmente las lanchas te dejan en el muelle pero el muelle ahorita está en mantenimiento Así que las lanchas te dejan acá cerca de El barco hundido y a mí me encantó esta opción Además de que no hay que caminar tanto para llegar hasta acá porque yo venía justo para acá para mostrarles esto está acá estos dos barcos hundidos de aquí hacen que todo sea mucho más espectacular porque acá ustedes pueden bucear yo voy a hacer snorkel yo me traje como todas mis cositas para poder grabar abajo del agua para que ustedes vean lo hermoso que se ve acá la vida Marina sobre todo en estos barcos hundidos que está como todo")

def test_save_to_supabase():
    print("Testing save_to_supabase...")
    try:
        # Save to Supabase
        save_to_supabase(TEST_ROOT, set(TEST_FORMS), "TEST")
        
        # Verify insertion
        response = supabase.table("words").select("*").eq("root", TEST_ROOT).execute()
        word_data = response.data
        if word_data:
            word_id = word_data[0]['id']
            print(f"Word '{TEST_ROOT}' inserted with ID: {word_id}")
            
            # Check WordForms
            form_response = supabase.table("wordforms").select("*").eq("word_id", word_id).execute()
            forms = form_response.data
            print(f"Forms for '{TEST_ROOT}': {forms}")
        else:
            print(f"Word '{TEST_ROOT}' not found in database.")
    except Exception as e:
        print(f"Error: {e}")

def test_get_video_words():
    print("Testing get_video_words...")
    
    # Test successful case
    video_id = "x7Yq9MJUqjY"  # Replace with an actual video ID that exists in your system
    try:
        result = get_video_words(video_id)
        print(f"Successfully retrieved words for video {video_id}")
        print(f"Number of words: {len(result)}")
        print(f"Sample words: {result[:5]}")  # Print first 5 words as a sample
    except HTTPException as e:
        print(f"Error retrieving words for video {video_id}: {e.detail}")

def test_get_missing_words():
    print("Testing get_missing_words...")
    
    # Use a test user ID - make sure this user exists in your Supabase
    test_user_id = "529cf561-a58a-4e90-9148-5e9b0f8c49e1"  # Replace with an actual test user ID
    
    # Use a test video ID - make sure this video exists in your system
    test_video_id = "x7Yq9MJUqjY"  # Replace with an actual video ID that exists in your system

    try:
        # Fetch the video words
        words = get_video_words(test_video_id)
        
        # Get the missing words for the user
        result = get_missing_words(test_user_id, words)
        print(f"Missing words for user {test_user_id}:")
        print(result)
    except HTTPException as e:
        print(f"Error getting missing words: {e.detail}")

def test_filter_non_spanish_words():
    print("Testing filter_non_spanish_words...")
    
    test_cases = [
        "Hola, mi nombre es John y trabajo para Microsoft en New York.",
        "El iPhone de Apple es muy popular en España.",
        "Me gusta el fútbol y juego FIFA en mi PlayStation. It is 5cm long.",
        "La Torre Eiffel está en París, pero yo prefiero visitar Barcelona.",
        "El curry es un plato típico de la India, no de México."
    ]
    
    for text in test_cases:
        try:
            filtered_text = filter_entities(text, 'spanish')
            print(f"Original text: {text}")
            print(f"Filtered text: {filtered_text}")
            print("---")
        except Exception as e:
            print(f"Error filtering text: {e}")

def test_filter_non_spanish_words_from_file():
    print("Testing filter_non_spanish_words with file input...")
    
    file_path = "/Users/victorfriedrich/lang/backend/tAyghTk40Mk.txt"
    
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            original_text = file.read()
        
        original_length = len(original_text.split())
        filtered_text = filter_entities(original_text)
        filtered_length = len(filtered_text.split())
        
        print(f"Original text length: {original_length} words")
        print(f"Filtered text length: {filtered_length} words")
        print(f"Difference: {original_length - filtered_length} words removed")
        
        # Print a sample of the filtered text
        print("Sample of filtered text:")
        print(" ".join(filtered_text.split()[:50]))  # First 50 words
        
    except FileNotFoundError:
        print(f"Error: File not found at {file_path}")
    except Exception as e:
        print(f"Error processing file: {e}")


# Run tests
if __name__ == "__main__":
    #test_group()
    #test_parse()
    test_get_word_root()
    #test_generate_word_forms()
    # test_is_special_character()
    #test_parse()
    #test_save_to_supabase()
    #test_generate_alternatives()
    #add_to_dictionary("buscaré")
    #test_get_video_words()
    #test_get_missing_words()
    #test_filter_non_spanish_words()
    #test_filter_non_spanish_words_from_file()
