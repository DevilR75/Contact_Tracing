# GUI Tracker Application: Real-time tracking and querying using RabbitMQ
import tkinter as tk
import threading
import pika
import json
import time
import uuid

# Gen Z Theme
BG_COLOR = "#121212"          # Background color
TEXT_COLOR = "#EEEEEE"        # Text color
ACCENT_COLOR = "#FF007F"      # Accent color

# Global dictionary to store position messages from persons
# Key: person_id, Value: complete message (includes name, x, y, and timestamp)
positions = {}
positions_lock = threading.Lock()  # Lock for thread-safe access

# RabbitMQ connection settings and queue/exchange names
RABBITMQ_HOST = 'localhost'
EXCHANGE_NAME = 'positions'
CONFIG_REQUEST_QUEUE = 'config_request'
CONFIG_RESPONSE_QUEUE = 'config_response'
MAX_CANVAS_SIZE = 600  # Maximum canvas size in pixels

def get_board_size_from_tracker():
    """
    Request the board size from the tracker via RabbitMQ.
    Connects to RabbitMQ, sends a configuration request, waits for the board size response,
    and returns the board size.
    """
    connection_params = pika.ConnectionParameters(host=RABBITMQ_HOST)
    connection = pika.BlockingConnection(connection_params)
    channel = connection.channel()

    # Declare configuration queues for request and response
    channel.queue_declare(queue=CONFIG_REQUEST_QUEUE)
    channel.queue_declare(queue=CONFIG_RESPONSE_QUEUE)

    # Publish an empty JSON message to request board size
    channel.basic_publish(
        exchange='',
        routing_key=CONFIG_REQUEST_QUEUE,
        body=b'{}'
    )
    print("[GUI] Board size request sent...")

    board_size_holder = [None]

    # Callback to process the board size response
    def on_response(ch, method, properties, body):
        try:
            msg = json.loads(body)
            board_size_holder[0] = int(msg["board_size"])
        except Exception as e:
            print("[GUI] Error receiving board size:", e)
        ch.stop_consuming()  # Stop consuming after receiving a response

    # Consume the response from the CONFIG_RESPONSE_QUEUE
    channel.basic_consume(
        queue=CONFIG_RESPONSE_QUEUE,
        on_message_callback=on_response,
        auto_ack=True
    )
    channel.start_consuming()
    connection.close()

    if board_size_holder[0] is None:
        print("[GUI] Using default board_size = 10.")
        return 10
    else:
        print("[GUI] Received board_size:", board_size_holder[0])
        return board_size_holder[0]

def rabbitmq_consumer():
    """
    Create a RabbitMQ consumer that listens to position messages from the exchange.
    Stores each incoming message in the global 'positions' dictionary.
    """
    connection_params = pika.ConnectionParameters(host=RABBITMQ_HOST)
    connection = pika.BlockingConnection(connection_params)
    channel = connection.channel()

    # Declare the exchange and bind an anonymous queue to receive messages
    channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type='fanout')
    result = channel.queue_declare(queue='', exclusive=True)
    queue_name = result.method.queue
    channel.queue_bind(exchange=EXCHANGE_NAME, queue=queue_name)

    # Callback to process incoming position messages
    def callback(ch, method, properties, body):
        try:
            msg = json.loads(body)
            # Each message should include: name, person_id, x, y, timestamp
            person_id = msg["person_id"]
            with positions_lock:
                positions[person_id] = msg
        except Exception as e:
            print("Error processing message:", e)

    # Start consuming messages
    channel.basic_consume(queue=queue_name, on_message_callback=callback, auto_ack=True)
    print(f"GUI: Consumer started and bound to exchange '{EXCHANGE_NAME}'")
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        channel.stop_consuming()
    connection.close()

def query_person_via_rabbitmq(person_id):
    """
    Send a query message for the given person_id to the tracker.
    Waits for and returns the response containing current position and contacts.
    """
    connection_params = pika.ConnectionParameters(host=RABBITMQ_HOST)
    connection = pika.BlockingConnection(connection_params)
    channel = connection.channel()

    channel.queue_declare(queue='query')

    # Create an anonymous callback queue for the response
    result = channel.queue_declare(queue='', exclusive=True)
    callback_queue = result.method.queue

    correlation_id = str(uuid.uuid4())  # Unique ID for this request
    response_holder = [None]

    # Callback to process the query response
    def on_response(ch, method, properties, body):
        if properties.correlation_id == correlation_id:
            try:
                msg = json.loads(body)
                response_holder[0] = msg
            except Exception as e:
                response_holder[0] = {"error": str(e)}
            ch.stop_consuming()  # Stop after receiving the correct response

    channel.basic_consume(queue=callback_queue, on_message_callback=on_response, auto_ack=True)

    # Publish the query message with the given person_id
    query_message = {"person_id": person_id}
    channel.basic_publish(
        exchange='',
        routing_key='query',
        properties=pika.BasicProperties(reply_to=callback_queue, correlation_id=correlation_id),
        body=json.dumps(query_message).encode('utf-8')
    )
    print(f"[GUI] Query sent for person_id: {person_id}")
    channel.start_consuming()
    connection.close()
    return response_holder[0]

class TrackerGUI:
    def __init__(self, root, board_size):
        """
        Initialize the main GUI components: the canvas for displaying positions,
        the query input area, the query results panel, and the close button.
        """
        self.root = root
        self.board_size = board_size
        # Calculate cell size so that the grid fits within MAX_CANVAS_SIZE
        self.cell_size = max(1, int(MAX_CANVAS_SIZE / board_size))
        # Define margins for axis labels
        self.margin_left = 30   # Space for y-axis labels
        self.margin_bottom = 30  # Space for x-axis labels
        # Total canvas dimensions include the grid and margins
        self.canvas_width = self.margin_left + board_size * self.cell_size
        self.canvas_height = board_size * self.cell_size + self.margin_bottom

        self.root.title("GUI Tracker")
        self.root.configure(bg=BG_COLOR)

        # Main frame contains both the canvas (left) and the results panel (right)
        self.main_frame = tk.Frame(root, bg=BG_COLOR)
        self.main_frame.pack(expand=True, fill="both")

        # Left frame for grid visualization
        self.left_frame = tk.Frame(self.main_frame, bg=BG_COLOR)
        self.left_frame.pack(side=tk.LEFT, padx=10, pady=10)

        self.canvas = tk.Canvas(self.left_frame, width=self.canvas_width, height=self.canvas_height, bg="#222")
        self.canvas.pack()

        # Right frame for query input and displaying results
        self.right_frame = tk.Frame(self.main_frame, bg=BG_COLOR)
        self.right_frame.pack(side=tk.RIGHT, padx=10, pady=10, fill="both", expand=True)

        # Title label for the results panel
        title_label = tk.Label(self.right_frame, text="Tracking Results", font=("Helvetica", 16, "bold"),
                                bg=BG_COLOR, fg=TEXT_COLOR)
        title_label.pack(pady=10)

        # Frame for query input
        query_frame = tk.Frame(self.right_frame, bg=BG_COLOR)
        query_frame.pack(pady=10)
        query_label = tk.Label(query_frame, text="Enter Person Name:", font=("Helvetica", 12),
                               bg=BG_COLOR, fg=TEXT_COLOR)
        query_label.pack(side=tk.LEFT)
        self.query_entry = tk.Entry(query_frame, font=("Helvetica", 12), bg="#333", fg=TEXT_COLOR)
        self.query_entry.pack(side=tk.LEFT, padx=5)
        self.query_button = tk.Button(query_frame, text="Query", command=self.start_query,
                                      bg=ACCENT_COLOR, fg=TEXT_COLOR, font=("Helvetica", 12, "bold"))
        self.query_button.pack(side=tk.LEFT, padx=5)

        # Label for displaying the query results
        self.query_result_label = tk.Label(self.right_frame, text="", justify=tk.LEFT, wraplength=300,
                                           bg=BG_COLOR, fg=TEXT_COLOR, font=("Helvetica", 12))
        self.query_result_label.pack(pady=10)

        # Close button in the lower right corner to exit the application
        self.close_button = tk.Button(self.right_frame, text="Close", command=self.close_app,
                                      bg=ACCENT_COLOR, fg=TEXT_COLOR, font=("Helvetica", 12, "bold"))
        self.close_button.pack(side=tk.BOTTOM, anchor='e', padx=10, pady=10)

        # Start periodic update of the canvas
        self.periodic_update()

    def canvas_x(self, x):
        """Convert simulation x-coordinate to canvas x-coordinate."""
        return self.margin_left + x * self.cell_size

    def canvas_y(self, y):
        """
        Convert simulation y-coordinate (with 0 at bottom) to canvas y-coordinate.
        This maps (0,0) to the bottom-left of the grid.
        """
        return self.board_size * self.cell_size - y * self.cell_size

    def update_canvas(self):
        """
        Clear and redraw the grid along with all persons on the canvas.
        The grid is drawn in Cartesian style:
          - (0,0) is at the bottom-left.
          - X-axis labels are drawn below the grid.
          - Y-axis labels are drawn to the left, with the bottom row labeled "0".
        """
        self.canvas.delete("all")
        # Draw horizontal grid lines (for y from 0 to board_size)
        for i in range(self.board_size + 1):
            y_line = self.canvas_y(i)
            self.canvas.create_line(self.canvas_x(0), y_line,
                                    self.canvas_x(self.board_size), y_line,
                                    fill="gray")
        # Draw vertical grid lines (for x from 0 to board_size)
        for i in range(self.board_size + 1):
            x_line = self.canvas_x(i)
            self.canvas.create_line(x_line, self.canvas_y(0),
                                    x_line, self.canvas_y(self.board_size),
                                    fill="gray")
        # Draw x-axis labels below the grid
        for col in range(self.board_size):
            x_mid = self.canvas_x(col) + self.cell_size / 2
            y_label = self.board_size * self.cell_size + self.margin_bottom / 2
            self.canvas.create_text(x_mid, y_label, text=str(col), fill=TEXT_COLOR, font=("Helvetica", 10))
        # Draw y-axis labels to the left of the grid (Cartesian order: bottom cell labeled "0")
        for row in range(self.board_size):
            # The center of the cell with simulation y = row is at:
            y_mid = self.canvas_y(row) - self.cell_size / 2
            x_label = self.margin_left / 2
            self.canvas.create_text(x_label, y_mid, text=str(row), fill=TEXT_COLOR, font=("Helvetica", 10))
        # Draw each person from the global positions dictionary
        with positions_lock:
            for person_id, data in positions.items():
                x = data.get("x", 0)
                y = data.get("y", 0)
                cx = self.canvas_x(x) + self.cell_size / 2
                # Adjust y so that a simulation y of 0 appears at the bottom of the grid
                cy = self.canvas_y(y) - self.cell_size / 2
                r = self.cell_size / 3
                self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=ACCENT_COLOR)
                self.canvas.create_text(cx, cy, text=data.get("name", str(person_id)),
                                        fill=TEXT_COLOR, font=("Helvetica", 10, "bold"))

    def periodic_update(self):
        """Periodically update the canvas to reflect the latest positions."""
        self.update_canvas()
        self.root.after(50, self.periodic_update)

    def start_query(self):
        """
        Initiate a query based on the entered person name.
        Searches for all persons with a matching name (case-insensitive) and starts a query for each.
        """
        person_name = self.query_entry.get().strip()
        if not person_name:
            self.query_result_label.config(text="Please enter a valid Person Name.")
            return
        threading.Thread(target=self.run_query, args=(person_name,), daemon=True).start()

    def run_query(self, person_name):
        """
        Search for all persons matching the entered name.
        For each match, send a query to the tracker and format the result.
        The contacts list is joined with newlines so that each contact appears on its own line.
        """
        with positions_lock:
            matching = [(pid, data) for pid, data in positions.items() if data.get("name", "").lower() == person_name.lower()]
        if not matching:
            self.root.after(0, lambda: self.query_result_label.config(text=f"No persons found with name: {person_name}"))
            return

        results = []
        for pid, data in matching:
            response = query_person_via_rabbitmq(pid)
            name = data.get("name", "N/A")
            current_position = response.get("position", "N/A")
            contacts = response.get("contacts", [])
            # Join contacts with newline so that each appears in its own row
            contacts_text = "\n".join(map(str, contacts)) if contacts else "No contacts."
            result_text = (f"Name: {name}\n"
                           f"Person ID: {response.get('person_id', 'N/A')}\n"
                           f"Current Position: {current_position}\n"
                           f"Contacts:\n{contacts_text}")
            results.append(result_text)
        final_text = "\n\n".join(results)
        self.root.after(0, lambda: self.query_result_label.config(text=final_text))

    def close_app(self):
        """Close the application properly by destroying the main window."""
        self.root.destroy()

def main():
    """
    Main function to set up the GUI.
    Retrieves the board size from the tracker, starts the RabbitMQ consumer thread,
    and initializes the Tkinter GUI.
    """
    board_size = get_board_size_from_tracker()
    # Start RabbitMQ consumer in a separate thread to listen for position updates
    consumer_thread = threading.Thread(target=rabbitmq_consumer, daemon=True)
    consumer_thread.start()
    root = tk.Tk()
    gui = TrackerGUI(root, board_size)
    root.mainloop()

if __name__ == "__main__":
    main()
