from rich import print
import logging
import threading
import time
from rich.logging import RichHandler

from manager import ProxyFactory
from config import proxies
# Configure logging
logging.basicConfig(level=logging.INFO, handlers=[RichHandler()])

# Your dictionary

my_dict = ProxyFactory(proxies)
# Function to print and log changes
def print_and_log_changes():
    while True:
        global my_dict
        logging.info(f"Current dictionary: {my_dict.proxies}")
        time.sleep(1)  # Adjust the delay as needed

# Create a background thread for the print_and_log_changes function
background_thread = threading.Thread(target=print_and_log_changes, daemon=True)

# Start the background thread
background_thread.start()

# Example: Modify the dictionary in the main program
try:
    while True:
        # Simulate changes to the dictionary
        print(my_dict.get_proxy())

        # Perform other tasks in the main program

        # Add a delay to control the rate of changes
        time.sleep(0.6)

except KeyboardInterrupt:
    print("Program terminated.")

