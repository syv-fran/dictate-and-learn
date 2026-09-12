import io
import logging
import queue
import threading
import time

import transformers


class QueuePublisher:
    def __init__(self):
        self.active_queue = None
        self.lock = threading.Lock()

    def subscribe(self):
        new_queue = queue.Queue()
        with self.lock:  # kicks out previous subscriber
            self.active_queue = new_queue
        return new_queue

    def log(self, message):  # log only if we have a subscriber
        with self.lock:
            if self.active_queue is not None:
                self.active_queue.put(message)


# Custom method for logger: add the message to global progress:QueuePublisher
class ThreadSafeLogHandler(logging.Handler):
    def emit(self, record):
        progress.log(self.format(record))


# Same for library progress indicators that are written to streams such as stderr
class ProgressStream(io.StringIO):
    def write(self, buf):
        progress.log(buf)
        return super().write(buf)

def make_queue(logger):
    my_queue = progress.subscribe()
    logger.info("Starting log..")
    def generate_events():
        last_activity_time = time.time()
        heartbeat_interval = 8.0
        try:
            while True:
                try:
                    log_entry = my_queue.get(timeout=1.0)
                    print(f"Sending {log_entry=}")
                    last_activity_time = time.time()
                    yield f"data: {log_entry}\n\n"

                except queue.Empty:
                    current_time = time.time()
                    if current_time - last_activity_time >= heartbeat_interval:
                        yield ": tick\n\n"
                        last_activity_time = (
                            current_time  # do after yield so don't update if dropped.
                        )
                    continue
        except GeneratorExit:
            print("client closed logger")
        finally:
            print("logger finished")
    return generate_events

progress = QueuePublisher()
logger = None

def start(name:str)-> logging.Logger:
    global logger
    log_handler = ThreadSafeLogHandler()  # customised to add to 'progress' queue 
    log_handler.setFormatter(logging.Formatter(" %(asctime)s - %(module)s %(message)s"))
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.addHandler(log_handler)
    whisper_logger = logging.getLogger("whisperx")
    whisper_logger.addHandler(log_handler)
    #transformers logger has more features...
    hf_logger = transformers.utils.logging.get_logger("transformers")
    hf_logger.addHandler(log_handler)
    transformers.utils.logging.set_verbosity_warning()
    transformers.utils.logging.enable_progress_bar()
    return logger

def get() -> logging.Logger:
    if logger is None:
        raise RuntimeError("Logger not set up yet. Call setup() first.")
    return logger