import json
import time
import os
import signal
import sys
from nlp_processing import parse
from database import initialize_cache
from paths import data_file

# Global variable to track the last processed batch
last_processed_batch = 0
running = True

def signal_handler(sig, frame):
    """Handle keyboard interrupts gracefully"""
    global running
    print(f"\nProcess interrupted. Last completed batch: {last_processed_batch}")
    print("Shutting down gracefully... ")
    running = False

# Register the signal handler for Ctrl+C (SIGINT)
signal.signal(signal.SIGINT, signal_handler)

def load_json_file(file_path):
    """Load a JSON file containing a list of words."""
    with open(file_path, 'r', encoding='utf-8') as json_file:
        data = json.load(json_file)
    return data

def save_progress(start_batch, current_batch, file_path=str(data_file("processing_progress.txt"))):
    """Save the current processing progress to a file"""
    with open(file_path, 'w') as f:
        f.write(f"start_batch={start_batch}\n")
        f.write(f"current_batch={current_batch}\n")
        f.write(f"timestamp={time.time()}\n")
    print(f"Progress saved: completed through batch {current_batch}")

def load_progress(file_path="processing_progress.txt"):
    """Load the last processing progress from a file"""
    if not os.path.exists(file_path):
        return None
    
    try:
        progress = {}
        with open(file_path, 'r') as f:
            for line in f:
                key, value = line.strip().split('=', 1)
                progress[key] = value
        
        if 'current_batch' in progress:
            return int(progress['current_batch'])
        return None
    except Exception as e:
        print(f"Error loading progress file: {e}")
        return None

def process_batch(words, batch_number, batch_size, sub_batch_size, language):
    """Process a single batch of words"""
    global last_processed_batch
    
    start_index = (batch_number - 1) * batch_size
    end_index = min(batch_number * batch_size, len(words))
    
    words_to_process = words[start_index:end_index]
    total_words = len(words_to_process)
    processed_words = 0
    
    print(f"Processing batch {batch_number}: words {start_index+1} to {end_index} ({total_words} words)")
    
    for i in range(0, total_words, sub_batch_size):
        if not running:
            return False  # Exit if we received interrupt signal
            
        sub_batch = words_to_process[i:i+sub_batch_size]
        
        try:
            result = parse(sub_batch, "WORD_LIST", language)
            processed_words += len(sub_batch)
            print(f"Processed sub-batch {i//sub_batch_size + 1}, words {i+1} to {min(i+sub_batch_size, total_words)}")
        except Exception as e:
            print(f"Error processing sub-batch starting at index {i}: {e}")
    
    last_processed_batch = batch_number
    print(f"✅ Completed batch {batch_number} - Processed {processed_words} words")
    return True

def process_words_continuously(json_file_path, start_batch=1, batch_size=5000, language="french"):
    """
    Process words from a JSON file in batches and continue until finished or interrupted.
    
    Args:
        json_file_path: Path to the JSON file containing a list of words
        start_batch: Which batch to start processing from (1-based indexing)
        batch_size: Size of each batch
        language: Language of the words
    """
    global last_processed_batch
    
    # Check for saved progress
    saved_batch = load_progress()
    if saved_batch is not None and saved_batch >= start_batch:
        print(f"Found saved progress. Resuming from batch {saved_batch + 1}")
        current_batch = saved_batch + 1
    else:
        current_batch = start_batch
    
    # Initialize the cache for database lookups
    initialize_cache()
    
    # Load the words from the JSON file
    try:
        words = load_json_file(json_file_path)
        total_batches = (len(words) + batch_size - 1) // batch_size  # Ceiling division
        print(f"Loaded {len(words)} words from {json_file_path}")
        print(f"Total batches: {total_batches}")
    except Exception as e:
        print(f"Error loading JSON file: {e}")
        return
    
    # Sub-batch size for parse function (recommended: 50)
    sub_batch_size = 100
    
    # Process batches until completion or interruption
    try:
        while current_batch <= total_batches and running:
            success = process_batch(words, current_batch, batch_size, sub_batch_size, language)
            
            if success:
                # Save progress after each successful batch
                save_progress(start_batch, current_batch)
                current_batch += 1
            else:
                # If batch processing was interrupted
                break
        
        if current_batch > total_batches and running:
            print(f"✅ All batches completed! Processed batches {start_batch} through {total_batches}")
        else:
            print(f"Processing stopped at batch {current_batch}. Last completed: {last_processed_batch}")
            
    except KeyboardInterrupt:
        print(f"\nProcess manually interrupted. Last completed batch: {last_processed_batch}")
    except Exception as e:
        print(f"Error during processing: {e}")
        print(f"Last completed batch: {last_processed_batch}")
    
    return last_processed_batch

# Example usage
if __name__ == "__main__":
    json_file_path = str(data_file('french.json'))  # Your JSON file with the word list
    language = "french"  # Language of the words
    
    # Parse command line arguments if provided
    if len(sys.argv) > 1:
        start_batch = int(sys.argv[1])
    else:
        # Default to batch 1 or load from progress file
        saved_batch = load_progress()
        start_batch = saved_batch + 1 if saved_batch is not None else 1
    
    print(f"Starting word processing from batch {start_batch}")
    last_batch = process_words_continuously(json_file_path, start_batch, language=language)
    print(f"Processing complete or interrupted. Last processed batch: {last_batch}")