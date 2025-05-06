Great. I'll evaluate whether Docker is the best choice to manage architecture-independent execution (instead of venv) and/or to simulate client-server interaction. Then I'll deliver a full implementation plan with a complete `README.md` that explains the architecture, directory layout, test approach, linting, pre-commit hooks, documentation, and containerization strategy—all scoped to meet HD standard within 2,000 lines of code.


# Battleships: Engage in Explosive Rivalry (BEER) – Implementation Plan

## Project Overview

**Battleships: Engage in Explosive Rivalry (BEER)** is a networked Battleship game developed for the CITS3002 project. The aim is to meet all Tier 1–4 requirements at a High Distinction level, delivering full functionality with robust performance and code quality. Key constraints include maintaining a minimal codebase (under 2,000 lines of source), ensuring cross-platform compatibility (developed on Apple Silicon but runnable on x86_64 and other platforms), and providing a clean packaging or containerization for ease of deployment. This plan outlines the recommended architecture, environment setup, and development practices to achieve these goals while enabling ease of development, testing, and submission.

## Runtime Environment Setup: Docker vs Virtual Environment

The repository now ships **ready-made container tooling** *and* retains the lightweight venv workflow.

### 1. Local venv (fast inner-loop)
```bash
python -m venv venv && source venv/bin/activate
pip install -r dev-requirements.txt
python -m beer.server  # run server on localhost:5000
```

### 2. Docker (cross-arch, one-command demo)

```bash
# Build multi-arch image (arm64 / amd64)
docker build -t beer .

# Single container server
docker run --rm -p 5000:5000 beer

# Compose-demo: 1 server + 2 auto-started clients
docker compose up --build --scale client=2
```

The **Dockerfile** is based on `python:3.11-slim`, installs only runtime deps (`cryptography`) and copies `src/beer`.
`docker-compose.yml` defines a `server` service and a `client` service that can be scaled arbitrarily for spectator stress-tests.

This hybrid approach keeps day-to-day edits snappy while guaranteeing the marker can spin the game on any machine with Docker.

## Containerization Strategy

**Client-Server Deployment:** The BEER game consists of a server and multiple clients. We need to decide if each should be containerized for testing and deployment:

* *Single Container (Monolithic):* We could run both the server and clients inside one container (for example, launching multiple processes inside a single Docker container). This is not ideal for simulating a real networked environment since all processes would share the same host and network interface. It would be closer to running them natively on one machine and would forfeit some isolation.
* *Multi-Container Setup:* A more realistic approach is to use separate containers for the server and each client, orchestrated with Docker Compose or a similar tool. **Docker Compose** allows defining multi-container applications and configuring their network so that the services can communicate appropriately. For example, one service in a `docker-compose.yml` could be the BEER server, and another service (scaled to multiple instances) could represent clients. Compose will create an isolated network where the containers can reach each other by service name, simulating different machines on a local network.

**Development vs. Testing Usage:** For daily development and manual testing, running the server and client processes directly on the host (in separate terminal windows or via a simple script) is straightforward and fast. It's easy to start one server process and then launch two client instances to simulate a game. Containerization is not strictly required in this scenario. However, for integration testing or ensuring the system works in a clean environment, Docker can be very useful. For instance:

* We can use Docker Compose to spin up a realistic environment where the server and clients run in isolation. This can catch issues such as assuming a local filesystem for communication or using `localhost` incorrectly (with Compose, the server might be referenced by a container hostname).
* The containerized setup can also be used in the demonstration or by markers to quickly launch everything without installing dependencies locally, if they choose.

**Recommendation:** Containerize primarily for consistency in testing and deployment, but do not mandate it for running the project. Specifically:

* Provide a **Dockerfile** that containerizes the application environment (Python and required packages). This can be used to run the server (and clients) in a controlled setting. The same image could be used for both server and client code to minimize maintenance.
* Provide a **Docker Compose** configuration (optional, for convenience) which defines a `server` service and a `client` service. This allows one-command startup of a full game environment, e.g., `docker-compose up --scale client=2` could launch one server and two clients automatically. This is useful for the development team or during a demo to simulate multiple players easily.
* Ensure that the project **can run without Docker** as well. The submission should not force the use of containers; the marker can simply run the Python scripts on their machine if they prefer. Docker is there as an additional option (and to guarantee cross-platform operation if needed), not as a requirement.

By using Docker for final verification and possibly the demo, we get the benefits of an isolated, reproducible environment. But by not depending on it exclusively, we keep things flexible and simple. This strategy means we can develop quickly with native execution and use containerization as a safety net and deployment aid. It meets the cross-platform requirement (via Docker for arm64/x86 parity) while still being accessible.

## Choice of Programming Language

**Preferred Language:** We recommend implementing BEER in **Python 3**. Python offers the cleanest path to success under the given constraints:

* **Conciseness and Rapid Development:** Python's syntax and rich standard library allow us to implement complex logic in far fewer lines of code than languages like C or Java. This is crucial for staying under the 2,000 LOC limit while still achieving full functionality. We can clearly express game rules and network logic with minimal boilerplate in Python, which reduces cognitive load and potential bugs. Faster development and easier debugging mean we can iterate to a robust solution within the project timeframe.
* **Cross-Platform Compatibility:** Python is inherently cross-platform; the same code runs on macOS, Linux, and Windows as long as a compatible interpreter is installed. We can develop on Apple Silicon using Python (which has an ARM64 build) and be confident the code will run on an x86_64 Linux server or any other environment with Python. By sticking to pure Python or architecture-agnostic libraries, we avoid issues with different architectures. (If needed, we can even use Python's `platform` or environment checks to adjust minor details, but likely unnecessary.)
* **Networking and Concurrency Support:** Python's standard library includes everything needed for this project (e.g., the `socket` module for networking, `threading` or `asyncio` for concurrency, and data structures for game state). We won't need to write low-level socket handling from scratch in C or deal with memory management, which saves lines and reduces errors. Python's high-level networking APIs allow rapid development of the client-server communication. Additionally, Python threads are sufficient for a turn-based game – the GIL (Global Interpreter Lock) does not hinder I/O-bound multitasking much, so we can handle multiple connections concurrently without custom thread pools in C, etc.
* **Maintainability and Readability:** A concise Python implementation is easier to read and maintain, which is important for the graders reviewing the code. The dynamic typing with optional type hints, and Python's clean syntax, will make our code self-explanatory in many places. Shorter code that's clear is less prone to bugs and easier to test thoroughly.
* **Performance Considerations:** Battleship is not computationally intensive – it involves checking coordinates and updating a 10x10 grid. Python can easily handle the load of multiple simultaneous games. Network I/O (which happens at human speeds in a turn-based game) will dominate, and Python can comfortably keep up with I/O using threads or async. If performance bottlenecks arise (unlikely in this context), Python has profiling tools and the option to optimize hotspots or use libraries. But initial analysis suggests even a basic Python solution will meet the needs with plenty of headroom.

*Alternatives:* We briefly considered languages like **Java** or **C** for their strong typing or efficiency. However, those would significantly increase development time and code size (for example, Java would require defining classes for messages, using verbose syntax for I/O, etc., and C would involve manual socket setup, memory management, and has greater risk of platform-specific bugs). Given the emphasis on a robust but minimal solution, Python provides the best balance of brevity, clarity, and adequate performance. It allows us to achieve a clean, deterministic implementation without excessive overhead.

## Architecture Overview

**System Architecture:** BEER will follow a classic **client-server architecture**. There will be one server process coordinating the game, and multiple client processes (one per player) connecting to the server over the network. All game logic and state are centralized on the server to keep clients simple and to maintain authoritative, single source-of-truth for the game status.

* **Server Responsibilities:** The server is the brain of the game:

  * It listens on a TCP socket for incoming connections from clients (players).
  * It authenticates or registers new clients (if needed) and pairs clients into games. For instance, the first two clients to connect will form Game 1. If a third client connects, they might wait until a fourth connects to form Game 2, and so on. (If the game is strictly two-player only, extra clients could either queue or be rejected once a maximum is reached, depending on requirements.)
  * It handles the **game loop** for each active game. This includes: tracking whose turn it is, receiving a move from the current player, updating the game state (hit/miss, ship sunk), and sending the result to both players. Then it toggles the turn and prompts the other player.
  * It enforces the rules: for example, not allowing a player to shoot the same coordinate twice, or ensuring players place a valid configuration of ships at the start. All validation occurs on the server to prevent any possibility of a cheating client gaining advantage.
  * It manages concurrency: multiple games can be run in parallel (Tier 3 requirement) by handling each game in a separate thread or asynchronous task. The server will isolate each game's state so they don't interfere with each other.
  * It detects end-of-game and declares winners. If a player has all ships sunk, the server notifies both sides of the outcome.
  * It handles error cases gracefully: if a client disconnects unexpectedly, the server will handle that event (socket closure) by cleaning up that game and informing the remaining player (perhaps declaring them the winner by forfeit, or allowing them to await a new opponent if the design permits). Similarly, if a client sends malformed data, the server can ignore it or send an error message without crashing.

* **Client Responsibilities:** Each client represents a player and handles the user interface and input:

  * On startup, the client connects to the server's IP/port. It may need to send an initial hello or receive a greeting to establish the connection (this could be as simple as the server immediately asking for ship placements).
  * The client prompts the player to set up their board (placing ships). The user will input positions for each ship (e.g., "Place Destroyer at B3 horizontal"). The client sends these placements to the server for validation/acknowledgment.
  * During gameplay, the client waits for the server's instructions on whether it's the player's turn or the opponent's turn. When it's the player's turn, the client prompts for a target coordinate to fire at, sends that to the server, and then waits for the result of that shot. When it's the opponent's turn, the client just waits for an update from the server about what the opponent did (e.g., "Your ship at D5 was hit" or "Opponent missed at H7").
  * The client maintains a local view of the game for the player's convenience: typically two grids – one for the player's own ships (marking hits received) and one for shots fired at the enemy (marking hits and misses made). After each server update, the client updates these displays.
  * The client handles user input validation (to the extent possible): e.g., it can prevent the user from entering an out-of-bounds coordinate or an invalid format, improving user experience. However, the server will *also* enforce validity, so the game isn't reliant solely on the client's checks.
  * In essence, the client is a relatively thin GUI/CLI layer on top of the game. It trusts the server's rulings. If the server says "miss", the client will reflect that; it doesn't try to recalculate game logic on its own (except maybe duplicating some for immediate feedback, but the source of truth is the server).

**Communication Protocol:** We will design a simple, clear text-based protocol for the client-server interaction. This ensures easier debugging and a small implementation overhead:

* Communication will likely be line-oriented ASCII text. For example, a client might send: `FIRE B7` to indicate a shot at column B, row 7. The server might respond with `HIT` or `MISS` (and possibly `SUNK <ship>` if that shot sank a ship).
* Another example: during setup, the client could send `PLACE A1 A5 Battleship` meaning a Battleship from A1 to A5. The server replies `OK` or `ERROR overlap`, etc.
* Turns can be coordinated by the server sending a message like `YOUR TURN` to one client and `WAIT` to the other. The client will only allow input when it receives `YOUR TURN`.
* The protocol will include messages for game over (`WIN` or `LOSE` sent to clients accordingly).
* We will document all message types and formats in the README for clarity. Using a custom text protocol avoids needing external libraries and keeps both client and server logic transparent. (Alternatively, JSON could be used to encode messages, which might be slightly heavier but more structured. Given the simplicity of required messages, we lean towards a custom plain-text protocol for minimal overhead.)

**Concurrency Model (Server):** The server must handle multiple client connections and potentially multiple games at once. We plan to use a **multi-threaded** approach on the server, as it aligns well with Python's strengths:

* The main server thread will accept new connections in a loop. For each incoming client, it will spawn a new thread (using `threading.Thread`) to handle communication with that client. This means reading from and writing to each client socket happens in that client's dedicated thread.
* When two client threads are ready (both have signaled they are in lobby waiting for a game), the server will assign them to a game session. This could be done by a game manager component: e.g., when a thread finishes reading ship placements from a client, it adds that client to a waiting queue. If the queue has two clients, the server pairs them and signals their threads that a game can start.
* Each pair of client threads will then interact according to the game loop: one thread waiting for that client's input, then sending it to the other, etc. They will synchronize via the shared game state (protected by locks if necessary). Another design is to spawn a separate **game thread** to orchestrate between the two client threads, but that may be unnecessary complexity – the clients can effectively ping-pong under server coordination.
* Python's **GIL** ensures only one Python bytecode thread executes at a time, but since most of our operations are I/O-bound (waiting for client input or sending data), the GIL won't be a bottleneck. Threads will spend a lot of time blocked on socket I/O, during which other threads can run. This approach is a straightforward way to manage parallelism and is a common pattern for socket servers.
* We will be careful with shared data. For example, if we keep a global list of active clients or games, we'll use thread-safe operations or simple locking around modifications to that list. The game state for each match (the boards, whose turn, etc.) will be contained in an object that only the relevant two client threads access, so contention is minimal.
* An alternative was to use `asyncio` for a single-threaded asynchronous server. While that could handle many connections with low overhead, it makes the code flow a bit harder to follow for beginners and could introduce complexity (e.g., ensuring one game's messages don't mix with another's in the async loop). Given the moderate scale of clients and our focus on clarity, the threaded model is the better choice here.

**Deterministic Behavior:** We design the system to behave deterministically across runs and platforms. That means no race conditions or timing issues that could cause different outcomes. The turn-based nature simplifies this: at any given time, only one move is the "valid" action, and the server enforces that order. Even if both clients were to somehow send a move at nearly the same time (e.g., due to network jitter), the server will process them in a defined sequence (e.g., by timestamps or by rejecting the out-of-turn command). We may incorporate a simple timestamp or sequence number in messages if needed for arbitration, but likely the protocol design already prevents ambiguity (since a client should only send when it's their turn).

Random elements (if any) will be controlled. For example, if the server randomly chooses which player starts first, we will either fix a rule (like the first connected player starts) or use a random generator with a seed, so that tests can predict the flow if needed. Ship placement is by players, so that's not random from the system's perspective.

By using the same Python version and libraries on all platforms (ensured via Docker or matching installations), and by structuring the code to avoid undefined behavior, the game will run the same on an M1 Mac or an Ubuntu server. We will test on both architecture types to verify this consistency. In summary, the combination of a clearly defined turn order protocol and using a high-level language runtime that abstracts away OS differences will result in deterministic cross-platform execution.

## Implementation Plan by Component

To systematically build the project, we break the implementation into stages and components:

* **1. Game Logic Module:** Start by implementing the core battleship game logic in a standalone module (e.g., `game.py`). This module will define classes or functions for the board, ships, and rules:

  * Represent the board (10x10 grid) and the placement of ships on it. We can use a simple data structure (like a 10x10 list of lists, or a dictionary keyed by coordinates) to track positions.
  * Define the ship types (Carrier, Battleship, etc.) and their lengths. This can be a constant list or dict in the module.
  * Implement functions to place a ship on the board (ensuring no overlap and within bounds), to take a shot at a coordinate, and to check if all ships of a player are sunk (win condition).
  * These functions should be deterministic and side-effect free where possible (e.g., a `place_ship` function returns success or failure rather than printing anything).
  * Write **unit tests** for this logic (in `tests/test_game.py`). For example, test that placing ships in various configurations yields the expected outcomes, and that hitting all parts of a ship triggers a sunk state.
  * By doing this first, we separate concerns: the game rules are independent of networking. We ensure the game mechanics are correct and then use them in the server.

* **2. Server Implementation:** Develop the server in phases:

  * Initially, implement a basic server that can handle a single game between two clients. This involves accepting two connections, then entering a loop to alternate receiving a move from one and sending updates to the other. This will help prove out the protocol and basic networking.
  * Expand the server to manage multiple games concurrently. Introduce a structure to hold multiple game sessions. When a client connects, if there's an unmatched player waiting, pair them; otherwise, put them in a waiting state. We could maintain a queue (`waiting_clients`) for this purpose.
  * Use **threads** for each connected client. Each client thread will likely run a loop: read messages from that client and process them (either applying to a game state or handling meta-commands). The server might also have threads dedicated per game, but it might be sufficient that the two client threads interacting in a game share the game state and coordinate via that.
  * Integrate the game logic module: e.g., when a client thread receives a "FIRE X Y" command, it calls the `game.shoot(x,y)` function from the game module for that player's game, then prepares a response based on the return (hit/miss/sunk). This way, we don't rewrite game logic in the server, we just interface with it.
  * Handle special cases: If a client disconnects (`recv` returns empty), signal the game that the other player won by default and terminate that thread. If the server receives a message it doesn't understand, respond with an error or ignore it.
  * Ensure thread-safe access: when updating shared structures like `waiting_clients` or when two threads both might try to send to their clients at the same time, use locking or other synchronization to avoid garbling messages. (One strategy is to use a separate lock per game for sending outputs, or simply structure code so that only one thread sends at a time for a game.)
  * **Testing:** At this stage, test the server with dummy or actual clients. For example, one can use `telnet` or `nc` to simulate clients (since the protocol is text, you can type commands manually to test). We will also write a simple test script (or reuse the client code in a test mode) to automate connecting two clients to the server and playing a scripted sequence of moves, verifying the server's responses.

* **3. Client Implementation:** In parallel or after the server baseline, implement the client:

  * The client can be implemented as a console application (to avoid GUI overhead). It will likely run an input loop in the main thread and have a background thread listening for server messages, or use non-blocking I/O so it can check for server messages while waiting for user input.
  * Use the protocol specification to handle incoming messages. For example, if the client receives `HIT` or `MISS`, update the display grid accordingly. If it receives `YOUR TURN`, that signals the user can input a move.
  * Implement a nice text-based UI: This could be as simple as printing the boards in ASCII. We can use coordinates labeling (A-J for columns, 1-10 for rows) so the user can reference them. We'll update these prints each turn. Ensuring the console output is clear (maybe clearing screen between turns, or printing incrementally) is part of polish.
  * The client should also be robust to server disconnects (if server closes, the client should catch the EOF and exit gracefully with a message).
  * Once the client is ready, perform an **end-to-end test**: run the server and two clients and actually play a game of Battleship to completion. This will likely reveal any synchronization issues or minor protocol adjustments needed.
  * Incorporate any additional features (for higher tiers) into client and server together. For example, if a **chat** feature (text messaging between players) is a Tier 4 requirement, we would allocate a special command like "CHAT <message>" that the client can send at any time (or when allowed) and the server relays to the other client. We would implement that towards the end if time permits, ensuring it doesn't break the core game flow. Similarly, a spectator mode might mean additional clients can join a game in a read-only capacity; the server would then broadcast moves to those clients as well. These features would be carefully integrated if required, making sure to stay within LOC and complexity limits.

* **4. Quality Assurance and Refinement:** With the core functionality in place, we will rigorously test and refine:

  * **Automated Tests:** Use the `tests/` suite to run not just unit tests but possibly some integration tests (using sockets in a controlled environment). We can use `pytest` to orchestrate running a server in a thread and clients in threads to simulate a full game and assert outcomes. This ensures our code is deterministically handling the sequence of events.
  * **Cross-Platform Testing:** Run the program on at least two different platforms (e.g., macOS locally, and a Linux VM or container). Ensure that everything (especially file paths, line endings, case-sensitivity in any file operations if any, etc.) works the same. Since we are mostly network and console I/O bound, there should be little variation.
  * **Performance Testing:** While not a primary concern, we might test how the server behaves with, say, 4 or 6 clients (2–3 games) at once to ensure the thread model scales and there are no deadlocks or resource issues. If our design is efficient, we could even push it to dozens of clients just to be confident. Python can handle many threads if they're mostly idle waiting for I/O, so we expect it to be fine.
  * **Code Review:** As a final step, review the code to remove any redundancy or unused code (keeping LOC low), add comments or adjust naming for clarity, and ensure consistency (via linting tools as discussed later). This is where we ensure the code is clean enough for submission.
  * **Exception Handling:** Make sure that any potential exceptions (like invalid list indices, value errors on converting input strings to coordinates, etc.) are caught and handled so the program doesn't crash. Robustness is key for HD: the server should ideally never crash even if a client behaves unexpectedly; likewise, a client should handle server-side anomalies gracefully.

* **5. Containerization & Packaging:** Finally, set up the distribution aspects:

  * Write the **Dockerfile** to containerize the application. Likely we base it on `python:3.11-slim` (for example) and copy our code into `/app`, install requirements, and set the default entrypoint to the server (for convenience). We will ensure the Dockerfile is multi-arch capable by using an official base (which typically supports arm64 and amd64).
  * Create a **docker-compose.yml** (if using) for spinning up a server and multiple clients. For instance, it might define `beer-server` and `beer-client` services. We might not use this in submission unless demonstrating, but we will include it in the repository for completeness.
  * Prepare the final **README.md** (this document) with usage instructions, so the marker knows exactly how to run the server, how to start clients, and how to run tests or view the demo.
  * Ensure all necessary files are included and unnecessary files (like test logs, compiled bytecode, etc.) are excluded in the submission package.

Following this plan, we incrementally build a working solution, ensuring at each step that we meet the requirements and maintain code quality. By dividing the work into modules (game logic, server, client), we can parallelize development if in a team and reduce complexity at any single point.

## Directory Layout (src-layout)

The project will be organized in a clear, logical structure as follows:

```
beer-project/
├── README.md               # Detailed instructions and documentation (architecture, usage, etc.)
├── src/beer/
│   ├── server.py           ← lobby + matching
│   ├── client.py           ← framed client / chat
│   ├── session.py          ← per-match FSM, spectators, reconnect
│   ├── battleship.py       ← game rules
│   └── common.py           ← frame, CRC-32, AES helpers
├── requirements.txt        ← runtime deps only (cryptography)
├── Dockerfile              # Dockerfile for containerizing the application
├── docker-compose.yml      # (Optional) Compose file for multi-container setup (for testing/demo)
├── tests/                  # Test suite (if using pytest or similar)
│   ├── test_game.py        # Unit tests for game logic
│   └── test_integration.py # Integration tests for client-server (could simulate a game)
└── docs/                   # (Optional) Additional documentation or resources
    └── demo_scenario.txt   # Example input/output or scripted game scenario for reference
```

**Notes:**

* We keep the top-level simple. The core code files (`server.py`, `client.py`, `game.py`) live at the project root for easy access. This is a small project, so a single Python package or module namespace is sufficient. We will ensure these scripts have appropriate shebangs or can be invoked with `python3 server.py` etc.
* If the project grows, we could convert it into a package (e.g., a `beer/` directory with an `__init__.py` and submodules), but given the LOC limit, a flat structure is acceptable and easy to navigate.
* The `common.py` module (optional) would store things used by both server and client, such as the protocol message formats or utility functions to convert between board coordinates and internal indices. This avoids duplicating code in server.py and client.py.
* The `tests/` directory is included for completeness, though in a submission, the focus is on the application itself. If automated testing by the instructors is expected, they may provide their own tests. Our tests are mainly for development assurance.
* The `docs/` folder may include any supplementary materials (not strictly required). For example, we might include a text file describing a sample game or listing the exact rubric mapping (Tier 1-4 features) and how we addressed them, to make grading easier. This can be referenced in README.

This layout ensures a clear separation of concerns and will be explained in the README so that anyone looking at the repository knows where to find each piece.

## Development Practices (Typing, Linting, and Hooks)

To achieve a High Distinction level of code quality and maintainability, we will adopt several development best practices:

* **Static Typing with MyPy:** We will use Python's optional type hints per PEP 484 throughout the code. Annotating function signatures and key variables (e.g., the types for coordinates, the structures for boards and ships) will make the code easier to understand and serve as machine-checked documentation. During development, we'll run the **MyPy** type checker to catch inconsistencies or incorrect uses of data types. Static typing can catch bugs earlier in development and improve reliability, which is valuable in a project of this size. Even though Python doesn't enforce types at runtime, using them will not add much overhead in LOC and will signal our attention to detail.
* **Code Style and Linting:** We will enforce PEP 8 style conventions. Tools like **Flake8** or **Pylint** will be part of our workflow to identify any deviations or potential issues (unused variables, redefined names, etc.). This ensures the code is consistent in formatting and style, which is part of a polished submission. It also catches simple mistakes (for instance, using an undefined variable due to a typo).
* **Auto-formatting:** We plan to use **Black** (the uncompromising Python code formatter) to automatically format our code. This saves time and eliminates any debates or inconsistencies in code style. It will format our code in a standard way, so the diffs are clean and the code looks professional.
* **Pre-commit Hooks:** To tie the above tools together, we will set up **pre-commit hooks** in our git repository. Using the *pre-commit* framework, we can configure a set of checks that run every time we attempt to make a commit. For example, we will install hooks for Black and Flake8. This means *before* any code is committed, Black will reformat the code and Flake8 will check for issues; only if these pass will the commit go through. This automation ensures that the codebase remains clean at all times without requiring the developers (us) to remember to run these tools manually on each change. It reduces time spent on formatting and lets us focus on logic. Moreover, it demonstrates to the examiners that the code was consistently vetted for quality.
* **Continuous Testing:** Although a full continuous integration pipeline might be overkill for a student project, we will at least manually run our test suite frequently and especially before submission. If possible, we might use a GitHub Actions CI to run tests on push, including running on multiple platforms (there are free CI runners for Ubuntu, Windows, MacOS). This would further ensure cross-platform compatibility. Even if not set up, the principle is to test often and in environments other than our development machine.
* **Documentation:** We will document the code using docstrings for modules and complex functions. Given the LOC limit, we will keep comments and docstrings concise, but critical sections (like the server game loop or the protocol parsing logic) will have explanatory comments. Good documentation is part of a HD criteria. The README (this document) will serve as comprehensive documentation for usage and design, while the code comments will clarify tricky implementation details.
* **Version Control:** The use of Git is implicit; we'll make frequent commits with clear messages. This not only helps our development process but also provides a trace of how the project evolved (which could be of interest to a marker). With pre-commit hooks, we ensure each commit is in a good state (tests passing, lint clean).

By following these practices, we minimize the chances of late-stage surprises (like a trivial bug causing a crash during the demo or marking). It also showcases a level of professionalism in the submission — indicating that the project wasn't just "hacked together" but engineered with care and discipline, as expected for a High Distinction.

## Running and Testing the Project

We will provide clear instructions for running the server, clients, and tests in the README (as illustrated below). This ensures the markers can easily execute our project and verify all features:

**Running the Server and Clients (locally without Docker):**

1. **Install Dependencies:** Ensure Python 3 (preferably 3.10 or 3.11) is installed. Then install the required packages in an isolated environment:

   ```bash
   python3 -m venv venv
   source venv/bin/activate        # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

   *If no external libraries are used beyond the standard library, this step may be skipped, but we include it for completeness (e.g., if we use `pytest` or `colorama` for colored output).*
2. **Start the Server (plaintext):**

   ```bash
   python -m beer.server --port 5000
   ```

   **Encrypted mode** (default demo key):

   ```bash
   python -m beer.server --port 5001 --secure
   ```

   The server will start listening on the default port (e.g., 5000). You should see a message like `Server listening on port 5000...` indicating it's ready. (If needed, the port could be changed with a command-line argument or config file; we will document that in the README. For example: `python3 server.py --port 6000`.)
3. **Start a Client:** In a **new terminal** (with the venv activated as well), run:

   ```bash
   python -m beer.client --host 127.0.0.1 --port 5000
   ```

   For encrypted session:

   ```bash
   python -m beer.client --secure --port 5001
   ```

   This will connect the client to the server we just started (which is running on localhost:5000). If the server is on a different machine or Docker container, the `--host` option can target the appropriate IP. Launch a second client in another terminal with the same command to have two players in the game.
4. **Play the Game:** Once two clients are connected, the server will pair them and likely ask both to place their ships. Each client will prompt its user to enter ship placements (following the format we specify, e.g., typing coordinates or using an interactive method). After placement, the server will inform one player that they can start. The client will prompt that player to enter a coordinate to fire. The other client will wait and then receive the result of the shot. They will alternate turns until the game concludes. All these interactions will be visible in the client terminal outputs.

   * During gameplay, try entering an invalid command (like an out-of-bounds coordinate) to see how the system responds (it should handle it gracefully).
   * After one game finishes (win/lose message received), the server might either terminate those client connections or allow a new game. By default, we may close the connections and require restarting the client for a new game (to keep things simple). The README will clarify this behavior.

**Running with Docker:**

1. **Build the Docker Image:**

   ```bash
   docker build -t beer-game .
   ```

   This uses the provided Dockerfile to create an image containing our application. The `-t beer-game` tags the image for easy reference.
2. **Run the Server in a Container:**

   ```bash
   docker run --rm -p 5000:5000 --name beer-server beer-game python3 server.py
   ```

   This command launches the server inside a container. We publish port 5000 to the host, so that clients (whether running on host or in other containers) can connect. The server should start up as before, now running in Docker.
3. **Run Client(s) in Container(s):** If you want to run clients in containers as well (for example, to simulate multiple machines entirely in Docker), you can do so:

   ```bash
   docker run --rm --name beer-client1 --network container:beer-server beer-game python3 client.py --host 127.0.0.1 --port 5000
   ```

   In this command, we attach the client container to the server container's network namespace (using `--network container:beer-server` for simplicity), so it can reach the server on localhost:5000 as seen from that namespace. Alternatively, we could start all containers on a user-defined network or use Docker Compose which handles networking automatically.

   * **Using Docker Compose:** For convenience, we can simply run `docker-compose up` if the compose file is configured. This could, for instance, start one server and two client containers immediately. We will document the exact usage in the README. Compose will ensure the clients and server share a network and can resolve each other by service name.
4. **Stop Containers:** When finished, stop the server container (Ctrl+C if it's running in the foreground, or `docker stop beer-server`). If using Compose, `docker-compose down` will clean up all containers. We make sure that stopping and restarting the containers does not lead to residual state (the server doesn't keep state between runs unless explicitly saved, which we don't do here).

*Note:* The Docker approach is mainly for testing in a controlled environment. For actual play, running natively might be more convenient (to easily open multiple client terminals). We provide both options to be thorough.

**Running Tests:**

* If using **pytest**, simply run `pytest` in the project directory (after activating the venv and installing dev requirements if needed). All tests in the `tests/` folder should execute. This will test game logic and some integration flows.
* We might also include a small script `tester.py` that connects to the server and runs through a predetermined game (for example, to automate a sequence of moves). This could be used by the marker to verify a full game quickly. Instructions for such a script (if provided) will be in the README.
* Memory and resource usage can be observed during tests (e.g., using OS tools) but given the simplicity we expect minimal footprint.

By following the above instructions, the user (or marker) can easily set up a game and verify all features. We will ensure these steps are accurate by testing them ourselves on a clean setup before submission.

## Demo Video and Submission

We will create a demo video to showcase the project in action and prepare the submission package according to requirements:

* **Demo Video Outline:** The video (screencast with narration) will illustrate:

  * The project environment: show the repository structure briefly, then focus on running the program.
  * Launching the server (terminal window showing the server starting).
  * Launching two client instances. We'll arrange the windows side by side if possible to see both players' perspectives.
  * Walk through the gameplay: each player will place ships (we may use predetermined placements to save time). Then we demonstrate a few turns: Player A fires, we show the result on both sides; Player B fires, and so on. We ensure to demonstrate a **hit**, a **miss**, and the sinking of a ship (so viewers see the different message types and client responses).
  * Continue until one player wins. The winning and losing messages are shown.
  * We will also demonstrate robustness: for example, try to input an invalid coordinate like "Z10" and show that the client or server handles it (either by reprompting or giving an error message). We might also briefly show what happens if a client disconnects (e.g., close one client program mid-game and show the server detecting it and the other client being notified).
  * The video will conclude by stating that all required features were shown and perhaps a quick mention that the code is under 2000 LOC and uses the described architecture.
  * We aim to keep the video concise (likely 5-10 minutes) while covering all critical elements. This video would be suitable for the "project demonstration" component if required by the unit (some units require an in-person or recorded demo).

* **LMS Submission Instructions:**

  * We will submit a single **ZIP file** containing the entire project directory. The README.md, all code, and the Dockerfile/Compose file will be included. We will exclude any large files not needed (e.g., we won't include the `venv` folder or Python bytecode files).
  * The demo video will be either included in the ZIP (if size allows) or uploaded separately according to instructions (possibly on a platform like YouTube or Echo360 if an online link is preferred). We will ensure the marker has access to it.
  * Inside the README or as a separate short document, we will map the implemented features to the rubric (Tier 1–4) to make grading easier. For example, Tier 1 might be basic 1v1 game – implemented; Tier 2 might be input validation or a lobby system – implemented; Tier 3 concurrency – implemented (multiple games, shown in code or via test); Tier 4 additional features – implemented such-and-such. This is not explicitly required in the prompt, but it can help demonstrate we've covered everything.
  * We will double-check that the project runs in a fresh environment by simulating the grader's actions: download the zip to a new directory, follow the README steps exactly, and see that everything works. This guards against "it works on my machine" problems.
  * Lastly, we will include a note on the first lines of README or a separate file about the Python version and how to contact us (if needed) or where the code is hosted (if on GitHub, though typically submission is self-contained).

By meticulously following the above, we ensure that the marker can easily run and evaluate our project without any hiccups. The determinism across architectures is handled by either running our provided Docker setup or by the fact that we've tested on multiple architectures and documented any setup needed. The end result is a submission that is easy to run, demonstrates all features, and is packaged professionally.

## Strategies to Minimize Lines of Code

One of the challenges is to implement all required functionality within a 2,000 LOC limit. Here are the strategies we will use to keep the code compact yet clear:

* **Avoid Code Duplication (DRY Principle):** We will not repeat logic in multiple places. If both server and client need to do something (like parse a coordinate string "B7" into numeric indices), we'll implement it once (e.g., in `common.py` or in the game module) and reuse it. This reduces the total lines and also the surface for bugs. A single authoritative implementation of each piece of logic is easier to test and maintain.
* **Use Pythonic Constructs:** Python offers high-level constructs that accomplish tasks in one or few lines. We will use list comprehensions, generator expressions, and built-in functions like `any()` or `all()` to check win conditions (e.g., `all(ship.is_sunk() for ship in ships)` to determine if game over). This way, we avoid verbose loops when not needed. We will also leverage multiple return values (tuples) to return complex results from functions instead of needing separate variables.
* **Leverage Standard Library:** To keep code short, we'll use what's already available. For example, using the `queue.Queue` class for thread-safe communication between threads if needed (instead of implementing our own locking mechanism), or using `Enum` for ship types for clarity (which also provides some convenient printing, etc., with minimal code). The Python standard library is well-tested and using it prevents us from writing extra lines.
* **Keep Functions Focused:** By writing small, focused functions, each function tends to be shorter and we can reuse them in multiple contexts. For instance, a function `send_message(client_sock, msg)` can be used everywhere we need to send data, avoiding repeated try/except blocks for socket errors in multiple places. This not only saves lines but also makes it easier to update one part of behavior (like how errors are handled on send).
* **Minimal External Libraries:** Each external library can have its own weight (in usage and possibly in hiding complexity). We will rely only on what truly helps. For example, we might use `colorama` to color the terminal output for hits/misses (to make the game more visually appealing), but only if it can be done in a few lines and is worth it. We will not pull in heavy frameworks. This keeps our code self-contained and lines count low (also reduces the risk of multi-architecture issues).
* **Protocol Simplicity:** The text protocol means we can use simple `split()` and string operations to handle messages, which is typically just a couple of lines per message type. Had we chosen, say, a JSON protocol, we'd add some overhead (importing `json` and calling `json.dumps()/loads()` everywhere). Text parsing by hand can actually be shorter for our limited number of commands.
* **Automate repetitive tasks in code:** If we notice similar patterns, we'll abstract them. For instance, if each turn involves sending two messages (one to the shooter saying "you hit/missed" and one to the opponent saying "opponent hit/missed at X"), we can write a helper function `broadcast_result(game, coord, result)` to handle that in one place. Then the main game loop code is concise and reads like the rules ("get move; compute result; broadcast result; check win").
* **Exclude/test certain features if they threaten LOC:** We will prioritize core features over optional flourishes. If we start approaching the LOC limit, we will trim or simplify. For example, if we planned a fancy ASCII-art board display but it turns out too lengthy, we might simplify the rendering to a basic format. Or if a chat system is too much to implement fully, we might scale back to a simpler notification system. Meeting the base requirements reliably is more important than including every possible extra.
* **Commenting strategy:** We will write essential comments but avoid superfluous ones. Sometimes overly commenting every line can ironically bloat the code (and depending on how LOC is counted, it might count). We expect the markers count all lines including comments for the limit. So, we'll put detailed explanation in the README and only put necessary comments in code. This way, we keep code lean while the understanding can be derived from README + clean code structure.
* **Testing to avoid bug-fixes later:** A common source of extra lines is writing ad-hoc fixes for bugs discovered late. By testing early and often, we can implement things correctly the first time, avoiding writing patches or redundant checks later. A well-designed system might need fewer lines of defensive code.

By applying these strategies, we anticipate the total code will comfortably fit in the limit. Python's advantage in expressing ideas with fewer lines is a big factor here – a straightforward Python solution may only be on the order of 1000-1500 lines. We will keep an eye on the count and complexity at each stage, ensuring we don't introduce needless complexity that could also inflate line count. The end result will be a solution that is both **minimal** and **complete**, fulfilling all requirements without superfluous code.

## Conclusion

In summary, our plan for the BEER project is to build a robust, fully-featured Battleship game system using a client-server architecture in Python. We will use a hybrid environment setup: Python venv for development and optional Docker for cross-platform consistency, ensuring that the software runs deterministically on both arm64 and x86_64 systems. The architecture centers on a multi-threaded server that can handle multiple games in parallel and simple clients that interact with the user. We have outlined a clear implementation roadmap (game logic, then server, then client, then polish) that addresses all tier requirements progressively. By adhering to software engineering best practices like DRY, proper typing, linting, and thorough testing, we will keep the code quality high and free of bugs, which is essential for a High Distinction.

Crucially, we remain mindful of the 2,000 LOC limit and have adopted strategies to maximize functionality per line of code. The chosen language (Python) and design patterns enable us to meet the specification without bloat. We will deliver a comprehensive README (as exemplified by this document) to make running and evaluating the project straightforward. All in all, this setup provides an easy development cycle for us, a smooth testing process (including automated and cross-platform tests), and a painless experience for the graders to build, run, and assess the project. We are confident that following this plan will result in a successful implementation of BEER that meets and exceeds the project criteria.

#
## Tier 3 Deep-Dive — "Multiple Connections & Spectators"

Tier 3 HD requirements boil down to *scaling the social aspect* of the game without sacrificing determinism.

### 3.1 Multiple concurrent connections
The **lobby server** (`beer.server`) never blocks on `accept()`.  Every new socket is examined:

1. **Reconnect?** — If the first line starts with `TOKEN <hex>` it hands the socket to the existing `GameSession` via `attach_player` and resumes play.
2. **Spectator?** — If a match is in progress, `add_spectator()` registers the socket for read-only broadcasts (no extra threads created; writes piggy-back on the session's `_send`).
3. **Waiting lobby** — Otherwise the socket queues until another lonely player arrives, then a new `GameSession` thread is spawned.

### 3.2 Spectator experience
Spectators receive **the same framed packets** (GAME / CHAT) as players.  Client prints grids / chat but ignores turn prompts. Any command typed is answered with `ERR spectator` from the server.

### 3.3 Reconnection window (60 s)
Each player is issued an 8-byte token at `START`.  If the TCP link drops, the `GameSession` pauses, sets an `Event()`, and waits up to 60 s.  A reconnecting socket that sends `TOKEN <hex>` is re-attached (file objects swapped) and play continues.  If the timer expires the opponent wins by forfeit and spectators are informed.

### 3.4 Next-match selection
When a session ends, its thread terminates; the lobby loop immediately dequeues the next two waiting sockets (which could be freshly connected or long-time spectators) and starts the following match, broadcasting `INFO Next match begins…`.

All of the above is already live in the codebase (`session.py` & `server.py`) and covered by `tests/test_integration.py`.

## Compliance Matrix vs Project Brief (HD++)

The table below cross-references every requirement in *BEER_Project_Transcription.md* with the concrete artefact or implementation that satisfies it.

| Tier/ID | Requirement | Status | Reference (file / test) |
|---------|-------------|--------|-------------------------|
| **T1.1** | Fix concurrency bug | ✅ | `session.py` turn-lock; `tests/test_game.py::test_turn_order` |
| **T1.2** | Exactly two clients join | ✅ | `server.py` lobby pair logic |
| **T1.3** | Placement → play → win | ✅ | `battleship.py` rules; integration test |
| **T1.4** | Simple protocol | ✅ legacy line protocol preserved |
| **T1.5** | No disconnect handling req. | ✅ superseded by Tier 2 logic |
| **T2.1** | Input validation | ✅ | `session.py::parse_command` |
| **T2.2** | Multiple games | ✅ | `server.py` queue; threading |
| **T2.3** | 30 s inactivity timeout | ✅ | `GameSession._inactivity_timer` |
| **T2.4** | Detect disconnects | ✅ | socket EOF check + forfeit |
| **T2.5** | Idle clients → lobby | ✅ | `server._waiting` queue |
| **T3.1** | >2 clients; spectators | ✅ | `session.add_spectator` |
| **T3.2** | Spectators get updates | ✅ | broadcast in `GameSession._send_all` |
| **T3.3** | 60 s reconnect | ✅ | `session.attach_player` token logic |
| **T3.4** | Next-match rotation | ✅ | lobby loop after thread exit |
| **T4.1** | Custom packet + CRC-32 | ✅ | `common.py` framing, tests |
| **T4.2** | Chat / IM channel | ✅ | `/chat` command; `PacketType.CHAT` |
| **T4.3** | Encryption layer | ✅ | AES-CTR payload encryption; `--secure` CLI flag on server & client |
| **T4.4** | Security flaws & fix | ✅ | `exploit_replay.py` demonstrates replay; encrypted mode rejects stale seq |

*Legend:* ✅ complete – all rubric IDs satisfied.
Encryption + replay mitigation cover the second Tier-4 bullet for HD++.

---

## HD Submission Checklist (Final)

- [ ] **Code ZIP** `<SID1>_<SID2>_BEER.zip` < 2 000 LOC, includes Docker artefacts, excludes venv & caches.
- [ ] **Report PDF** `<SID1>_<SID2>_BEER.pdf` ≤ 10 pages, contains packet diagrams, crypto flowchart, replay exploit analysis.
- [ ] **Demo Video** public link ≤ 10 min showing Tier 1-4 features and secure mode.
- [ ] **README** (HD plan) at repo root; identical to BEER_HD_Plan_README.md.
- [ ] **Pre-commit hooks** ensure Black, Flake8, Mypy, pytest all green.
- [ ] **Finalize encryption flag + replay exploit** (implemented; see scripts & CLI flags) |



---
