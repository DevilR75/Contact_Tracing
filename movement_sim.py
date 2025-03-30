# Khajiyev Amir A00122387,  Dmitriy Maul A00122400 , Samisha Verma A00120599 Saman Thapa Magar A00127870
# Movement Simulation program using RabbitMQ to publish position messages
import pika
import json
import random
import time

# RabbitMQ connection setup
RABBITMQ_HOST = 'localhost'  # Change if running remotely
EXCHANGE_NAME = 'positions'
CONFIG_REQUEST_QUEUE = 'config_request'
CONFIG_RESPONSE_QUEUE = 'config_response'

# Global grid size; default is 10 (will be updated from the tracker)
GRID_SIZE = 10

class Person:
    def __init__(self, name, speed):
        # Capitalize the first letter of the name if it's lowercase
        self.name = name.strip().capitalize()
        self.speed = speed  # Cells per second
        # Generate a unique ID to avoid duplicates across multiple runs
        self.person_id = random.randint(1000, 9999) # Assign a random ID
        # Initialize random starting position within the grid
        self.x = random.randint(0, GRID_SIZE - 1) # Random starting position
        self.y = random.randint(0, GRID_SIZE - 1)

    def move(self):
        """Make a move in a random direction (like a king's move in chess)."""
        dx, dy = random.choice([
            (-1, -1), (-1, 0), (-1, 1),
            (0, -1),          (0, 1),
            (1, -1),  (1, 0), (1, 1)
        ])
        # Update the position while keeping it within grid boundaries
        self.x = max(0, min(GRID_SIZE - 1, self.x + dx)) # Keep within bounds
        self.y = max(0, min(GRID_SIZE - 1, self.y + dy))

    def get_position(self):
        """Return current person data for publishing."""
        return {
            "name": self.name,
            "person_id": self.person_id,
            "x": self.x,
            "y": self.y,
            "timestamp": time.time()  # For compatibility with the tracker
        }

def publish_position(person, channel):
    """Publish the person's position to the RabbitMQ exchange."""
    position = person.get_position()
    channel.basic_publish(
        exchange=EXCHANGE_NAME,
        routing_key='',
        body=json.dumps(position)
    )
    # Print output without the timestamp field
    printed_output = {
        "name": position["name"],
        "person_id": position["person_id"],
        "current_position": {"x": position["x"], "y": position["y"]}
    }
    print("Sent:", printed_output)

def request_board_size(channel):
    """Request board size from the tracker."""
    # Declare the necessary queues
    channel.queue_declare(queue=CONFIG_REQUEST_QUEUE)
    channel.queue_declare(queue=CONFIG_RESPONSE_QUEUE)
    # Publish board size request
    channel.basic_publish(exchange='', routing_key=CONFIG_REQUEST_QUEUE, body=b'{}')
    print("[MovementSim] Board size request sent...")
    board_size_holder = [None]

    def on_response(ch, method, properties, body):
        try:
            msg = json.loads(body)
            board_size_holder[0] = int(msg["board_size"])
        except (json.JSONDecodeError, KeyError):
            print("[MovementSim] Invalid board size response, using default 10.")
            board_size_holder[0] = 10
        ch.stop_consuming()

    channel.basic_consume(
        queue=CONFIG_RESPONSE_QUEUE, on_message_callback=on_response, auto_ack=True
    )
    channel.start_consuming()
    return board_size_holder[0]

def main():
    # Prompt the user for name and speed
    name = input("Enter name (e.g., 'Bob'): ") or "Anonymous"
    # Capitalize first letter if not already capitalized
    name = name.strip().capitalize()
    speed_str = input("Enter speed (cells per second) [default 1.0]: ") or "1.0"
    try:
        speed = float(speed_str)
    except ValueError:
        speed = 1.0

    # Connect to RabbitMQ
    connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
    channel = connection.channel()

    # Request the board size from the tracker and update GRID_SIZE
    global GRID_SIZE
    GRID_SIZE = request_board_size(channel)
    print(f"[MovementSim] Using board_size = {GRID_SIZE}")

    # Declare the exchange for publishing positions
    channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type='fanout')

    # Create a Person object with the given name and speed
    person = Person(name, speed)
    print(f"Person {person.name} (ID: {person.person_id}) started at ({person.x}, {person.y}) with speed {person.speed}")

    accumulator = 0.0
    last_time = time.time()
    try:
        # Main simulation loop
        while True:
            current_time = time.time()
            dt = current_time - last_time
            last_time = current_time
            accumulator += person.speed * dt
            moves = int(accumulator)
            if moves > 0:
                for _ in range(moves):
                    person.move()
                publish_position(person, channel)
                accumulator -= moves
            time.sleep(0.01)  # Short pause 
    except KeyboardInterrupt:
        print("\nSimulation stopped.")
        connection.close()

if __name__ == "__main__":
    main()
