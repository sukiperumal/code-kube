import os
import sys
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import subprocess
import threading
import time

# Import our prediction model
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from models.predictor import KubernetesIssuePredictor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("k8s-predictor-api")

# Initialize FastAPI
app = FastAPI(
    title="Kubernetes Issue Predictor API",
    description="API for predicting Kubernetes cluster issues using ML models",
    version="1.0.0"
)

# Initialize the predictor
MODELS_DIR = os.environ.get("MODELS_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models"))
predictor = KubernetesIssuePredictor(models_dir=MODELS_DIR)

# Background collection task
collection_thread = None
collection_stop_event = threading.Event()

# API Models
class PredictionRequest(BaseModel):
    data_file: str
    time_steps: Optional[int] = 12
    threshold: Optional[float] = 0.5

class CollectionRequest(BaseModel):
    prometheus_url: str = "http://prometheus-server.monitoring.svc.cluster.local:9090"
    duration_minutes: int = 30
    namespaces: List[str] = ["default", "kube-system", "monitoring"]
    step: str = "15s"
    process: bool = True

class SimulationRequest(BaseModel):
    scenario_type: str  # resource, network, pod-failure
    namespace: str = "ml-scenarios"
    duration: int = 300
    pods: int = 5
    pattern: str = "random"
    cleanup: bool = True

class TrainingRequest(BaseModel):
    data_file: str
    threshold_percentile: Optional[int] = 95
    time_steps: Optional[int] = 12

class PredictionResponse(BaseModel):
    predictions: Dict[str, Any]
    timestamp: str
    model_info: Dict[str, Any]

# Helper functions
def run_collection_task(request: CollectionRequest):
    """Run collection task in background."""
    cmd = [
        "python3",
        "src/data_collection/collector.py",
        "--prometheus-url", request.prometheus_url,
        "--duration", str(request.duration_minutes),
        "--step", request.step
    ]
    
    if request.namespaces:
        cmd.extend(["--namespaces"] + request.namespaces)
    
    if request.process:
        cmd.append("--process")
    
    logger.info(f"Running command: {' '.join(cmd)}")
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = process.communicate()
    
    if process.returncode != 0:
        logger.error(f"Error collecting metrics: {stderr}")
        return None
    
    logger.info(stdout)
    
    # Extract the processed file path from stdout
    for line in stdout.split('\n'):
        if "Saved processed metrics to" in line:
            return line.split("Saved processed metrics to")[-1].strip()
    
    return None

def run_simulation_task(request: SimulationRequest):
    """Run simulation task in background."""
    script = None
    args = []
    
    if request.scenario_type == "resource":
        script = "src/simulation/resource_exhaustion.py"
    elif request.scenario_type == "network":
        script = "src/simulation/network_issues.py"
    elif request.scenario_type == "pod-failure":
        script = "src/simulation/pod_failures.py"
    else:
        logger.error(f"Unknown scenario type: {request.scenario_type}")
        return False
    
    args = [
        "--namespace", request.namespace,
        "--duration", str(request.duration),
        "--pods", str(request.pods),
        "--pattern", request.pattern
    ]
    
    if request.scenario_type == "pod-failure" and request.cleanup:
        args.append("--cleanup")
    
    cmd = ["python", script] + args
    logger.info(f"Running command: {' '.join(cmd)}")
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = process.communicate()
    
    if process.returncode != 0:
        logger.error(f"Error running simulation: {stderr}")
        return False
    
    logger.info(stdout)
    return True

def background_collection_task():
    """Run continuous background collection every 5 minutes."""
    while not collection_stop_event.is_set():
        try:
            request = CollectionRequest()
            data_file = run_collection_task(request)
            if data_file:
                logger.info(f"Collection succeeded, data saved to {data_file}")
                
                # Make predictions if we have a model
                try:
                    predictions = predictor.predict(data_file)
                    logger.info(f"Made predictions on latest data")
                except Exception as e:
                    logger.error(f"Error making predictions: {e}")
        except Exception as e:
            logger.error(f"Error in background collection: {e}")
        
        # Sleep for 5 minutes
        for _ in range(300):
            if collection_stop_event.is_set():
                break
            time.sleep(1)

# API Routes
@app.get("/")
async def root():
    return {
        "message": "Kubernetes Issue Predictor API",
        "docs": "/docs",
        "health": "/health",
        "ready": "/ready"
    }

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/ready")
async def ready():
    # Check if models are loaded or can be loaded
    try:
        loaded = predictor.load_models()
        return {"status": "ready", "models_loaded": loaded}
    except Exception as e:
        return {"status": "not ready", "error": str(e)}

@app.post("/predict", response_model=PredictionResponse)
async def predict(request: PredictionRequest):
    """Make predictions on provided data file."""
    if not os.path.exists(request.data_file):
        raise HTTPException(status_code=404, detail=f"Data file not found: {request.data_file}")
    
    try:
        # Update predictor time_steps if provided
        if request.time_steps != predictor.time_steps:
            predictor.time_steps = request.time_steps
        
        # Make prediction
        predictions = predictor.predict(request.data_file)
        
        if predictions is None:
            raise HTTPException(status_code=500, detail="Prediction failed")
        
        # Convert predictions to dict for response
        prediction_dict = predictions.to_dict()
        
        # Create response
        response = {
            "predictions": prediction_dict,
            "timestamp": datetime.now().isoformat(),
            "model_info": {
                "time_steps": predictor.time_steps,
                "threshold": request.threshold,
                "data_file": request.data_file
            }
        }
        
        return response
    except Exception as e:
        logger.error(f"Error in prediction: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/collect")
async def collect(request: CollectionRequest, background_tasks: BackgroundTasks):
    """Collect metrics from Prometheus."""
    try:
        background_tasks.add_task(run_collection_task, request)
        return {"status": "Collection task started", "request": request.dict()}
    except Exception as e:
        logger.error(f"Error starting collection: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/simulate")
async def simulate(request: SimulationRequest, background_tasks: BackgroundTasks):
    """Run a simulation scenario."""
    try:
        background_tasks.add_task(run_simulation_task, request)
        return {"status": "Simulation task started", "request": request.dict()}
    except Exception as e:
        logger.error(f"Error starting simulation: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/train")
async def train(request: TrainingRequest):
    """Train models on provided data."""
    if not os.path.exists(request.data_file):
        raise HTTPException(status_code=404, detail=f"Data file not found: {request.data_file}")
    
    try:
        # Update predictor time_steps if provided
        if request.time_steps != predictor.time_steps:
            predictor.time_steps = request.time_steps
        
        # Train all models
        predictor.train_all_models(request.data_file)
        
        return {
            "status": "Training completed",
            "models_dir": predictor.models_dir,
            "time_steps": predictor.time_steps
        }
    except Exception as e:
        logger.error(f"Error in training: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/start_background_collection")
async def start_background_collection():
    """Start background collection task."""
    global collection_thread, collection_stop_event
    
    if collection_thread and collection_thread.is_alive():
        return {"status": "Background collection already running"}
    
    collection_stop_event.clear()
    collection_thread = threading.Thread(target=background_collection_task)
    collection_thread.daemon = True
    collection_thread.start()
    
    return {"status": "Background collection started"}

@app.post("/stop_background_collection")
async def stop_background_collection():
    """Stop background collection task."""
    global collection_thread, collection_stop_event
    
    if not collection_thread or not collection_thread.is_alive():
        return {"status": "Background collection not running"}
    
    collection_stop_event.set()
    collection_thread.join(timeout=10)
    
    return {"status": "Background collection stopped"}

@app.on_event("startup")
async def startup_event():
    """Run on API startup."""
    logger.info("Starting Kubernetes Issue Predictor API")
    
    # Try to load models
    try:
        loaded = predictor.load_models()
        if loaded:
            logger.info("Successfully loaded models")
        else:
            logger.warning("Failed to load models, will need training")
    except Exception as e:
        logger.error(f"Error loading models: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """Run on API shutdown."""
    logger.info("Shutting down Kubernetes Issue Predictor API")
    
    # Stop background collection
    global collection_thread, collection_stop_event
    if collection_thread and collection_thread.is_alive():
        collection_stop_event.set()
        collection_thread.join(timeout=5)

if __name__ == "__main__":
    # Get port from environment or default to 8080
    port = int(os.environ.get("PORT", 8080))
    
    # Run the API server
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info") 