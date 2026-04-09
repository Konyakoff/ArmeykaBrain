# Архитектура проекта ArmeykaBrain

```mermaid

graph TD
    classDef user fill:#F47920,stroke:#333,stroke-width:2px,color:#fff,font-weight:bold;
    classDef proxy fill:#f1c40f,stroke:#333,stroke-width:2px;
    classDef app fill:#3498db,stroke:#333,stroke-width:2px,color:#fff;
    classDef service fill:#2ecc71,stroke:#333,stroke-width:2px,color:#fff;
    classDef db fill:#9b59b6,stroke:#333,stroke-width:2px,color:#fff;
    classDef external fill:#e74c3c,stroke:#333,stroke-width:2px,color:#fff;
    classDef file fill:#ecf0f1,stroke:#333,stroke-width:2px;

    User((Пользователь)):::user

    subgraph Infrastructure [Infrastructure & Networking]
        CF[Cloudflare DNS / Cache]:::proxy
        Nginx[Nginx Reverse Proxy]:::proxy
        Docker[Docker Compose]:::app
    end

    User -->|HTTPS| CF
    CF -->|Proxy Pass| Nginx
    Nginx -->|Static Files / JS / CSS| Nginx
    Nginx -->|/api/* (REST & SSE)| Docker

    subgraph Backend [Backend: FastAPI (Uvicorn)]
        Main[app/main.py<br/>API Endpoints]:::app
        
        subgraph Core [Core Modules]
            Config[config.py<br/>Pydantic Settings]:::file
            Exceptions[exceptions.py<br/>Global Handlers]:::file
            Prompts[prompt_manager.py]:::file
            Schemas[schemas.py<br/>Pydantic Models]:::file
        end

        subgraph Services [Services Layer]
            Orchestrator[core.py<br/>process_query_logic]:::service
            GeminiSvc[gemini_service.py]:::service
            ElevenSvc[elevenlabs_service.py]:::service
            DataLoader[data_loader.py]:::service
        end

        subgraph Database [Database Layer]
            DB_ORM[database.py<br/>SQLModel ORM]:::db
            Models_ORM[models.py]:::db
        end
    end

    Docker --> Main
    Main -->|Calls| Orchestrator
    Main -->|Calls| DB_ORM
    
    Orchestrator -->|Streams via Queue| Main
    Orchestrator -->|Step 1-3, Eval| GeminiSvc
    Orchestrator -->|Step 4 TTS| ElevenSvc
    Orchestrator -->|Saves Results| DB_ORM

    GeminiSvc -->|Loads context| DataLoader
    GeminiSvc -->|Loads templates| Prompts
    
    subgraph Storage [File Storage]
        SQLite[(dialogs.db)]:::db
        JSON_Prompts[prompts/*.json]:::file
        TXT_RAG[data/*.txt<br/>Knowledge Base]:::file
        Audio[static/audio/*.mp3]:::file
    end

    DB_ORM --> SQLite
    Prompts --> JSON_Prompts
    DataLoader --> TXT_RAG
    ElevenSvc -->|ffmpeg processing| Audio

    subgraph External [External APIs]
        GeminiAPI[Google Gemini 3.1 Pro API]:::external
        ElevenAPI[ElevenLabs API v3]:::external
    end

    GeminiSvc -->|HTTP/REST| GeminiAPI
    ElevenSvc -->|HTTP/REST| ElevenAPI

```
