"""
Mfano Bora Attachment System - Backend Server
Run: python main.py (or run through app.py in server mode)
"""

from fastapi import FastAPI, Depends, Query, HTTPException, UploadFile, File, Form, Request as FastAPIRequest, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketState 
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date, datetime, timedelta
import os
import shutil
import sys
import json
import random
import string
from pathlib import Path
import socket
import psutil
import platform

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Import from local files
from models import (
    User, AttacheeProfile, CoordinatorProfile, SupervisorProfile, PushSubscription,
    Application, LogbookEntry, Attendance, LeaveRequest, Message, Report, Task, 
    Department, Notification, ApplicationForm, Interview, Contract, PerformanceReview, 
    PasswordResetRequest, SystemLog, SystemSetting, BackupHistory, DisableRequest,
    Training, TrainingAttendance, TrainingParticipant,
    # Resource management models
    Resource, ResourceAllocation,
    # Disciplinary management models
    DisciplinaryCase, ComplianceRecord, Commendation,
    # Challenges & Risk management models
    Challenge, Risk, MitigationPlan,
    # Suggestion management models
    Suggestion,
    # Meeting/Event models
    Event, EventParticipant,
    # Payment model
    Payment, ReginaLetter, ReginaTodo, ReginaGeneratedReport
)
from config import Config
from database import get_db_local, engine, Base

def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    
    return os.path.join(base_path, relative_path)

def get_face_cascade():
    """Get face cascade classifier - works in both script and EXE mode"""
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
        cascade_path = os.path.join(base_path, 'haarcascade_frontalface_default.xml')
    else:
        cascade_path = 'haarcascade_frontalface_default.xml'
    
    if os.path.exists(cascade_path):
        print(f"âœ… Loaded cascade from: {cascade_path}")
        return cv2.CascadeClassifier(cascade_path)
    else:
        print(f"âŒ Cascade file not found at: {cascade_path}")
        return None

# ==================== AUTHENTICATION DEPENDENCIES ====================

def get_current_user(request: FastAPIRequest, db: Session = Depends(get_db_local)):
    """Get current user from session or token."""
    # Method 1: Check for user_id in headers (for desktop app)
    user_id = request.headers.get("X-User-Id")
    
    if user_id:
        try:
            user = db.query(User).filter(User.id == int(user_id), User.is_active == True).first()
            if user:
                return user
        except:
            pass
    
    # Method 2: Check for session token in cookies (for web interface)
    token = request.cookies.get("session_token")
    if token:
        # Implement your session token validation here
        # For now, return a default or raise exception
        pass
    
    # Method 3: For development - return a default IT Manager user
    # This is only for testing when authentication isn't fully set up
    # REMOVE THIS IN PRODUCTION!
    default_user = db.query(User).filter(User.role == "it_manager", User.is_active == True).first()
    if default_user:
        print("âš ï¸ Using default user for authentication (development mode)")
        return default_user
    
    raise HTTPException(status_code=401, detail="Not authenticated")


def get_contract_payment_details(user_id: int, db: Session):
    """Return the latest approved contract payment details for an attachee."""
    contract = db.query(Contract).filter(
        Contract.attachee_id == user_id,
        Contract.status == "approved"
    ).order_by(
        Contract.supervisor_approved_at.desc(),
        Contract.updated_at.desc()
    ).first()

    if not contract:
        return None

    total_fee = float(contract.total_fee or 0)
    amount_paid = float(contract.amount_paid or 0)
    completion_fee = float(contract.completion_documents_fee or 0)
    completion_paid = float(contract.completion_paid or 0)
    remaining_balance = max(0.0, (total_fee + completion_fee) - (amount_paid + completion_paid))

    return {
        "contract_id": contract.id,
        "contract_number": contract.contract_number,
        "supervisor_approved_at": contract.supervisor_approved_at,
        "coordinator_approved_at": contract.coordinator_approved_at,
        "status": contract.status,
        "mode": contract.mode or "physical",
        "total_fee": total_fee,
        "amount_paid": amount_paid,
        "completion_documents_fee": completion_fee,
        "completion_paid": completion_paid,
        "remaining_balance": remaining_balance,
        "payment_reference": contract.payment_reference,
        "completion_payment_reference": contract.completion_payment_reference,
    }

# Try to import psutil for system monitoring
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("âš ï¸ psutil not installed. System performance metrics will use fallback values.")
    print("   Install with: pip install psutil")

# Create tables (using the engine from database.py)
Base.metadata.create_all(bind=engine)

# ============================================
# DEFAULT IT MANAGER CREATION
# ============================================

def ensure_default_it_manager():
    """Create default IT Manager user if no users exist"""
    db = next(get_db_local())
    
    try:
        user_count = db.query(User).count()
        
        if user_count == 0:
            print("\n" + "=" * 60)
            print("âš ï¸ NO USERS FOUND - CREATING DEFAULT IT MANAGER")
            print("=" * 60)
            
            it_manager = User(
                username="itmanager",
                email="admin@mfanoboraafrica.com",
                full_name="System Administrator",
                role="it_manager",
                is_active=True,
                phone="+254700000000",
                password_set=True,
                first_login=True
            )
            it_manager.set_password("Admin@123")
            db.add(it_manager)
            db.flush()
            
            it_profile = SupervisorProfile(
                user_id=it_manager.id,
                department="Information Technology",
                position="IT Manager",
                employee_id="ITM001"
            )
            db.add(it_profile)
            
            db.commit()
            
            print("\nâœ… Default IT Manager created!")
            print("   Username: itmanager")
            print("   Password: Admin@123")
            print("\nâš ï¸ PLEASE CHANGE PASSWORD ON FIRST LOGIN!")
            print("=" * 60 + "\n")
        else:
            print(f"âœ… Database has {user_count} user(s). Default user not needed.")
        
    except Exception as e:
        print(f"âŒ Error: {e}")
        db.rollback()
    finally:
        db.close()

# Call the function
ensure_default_it_manager()

# Create FastAPI app
app = FastAPI(title="Mfano Bora Attachment System API", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create uploads directory
os.makedirs(Config.UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(Config.UPLOAD_DIR)), name="uploads")

# ==================== PUSH NOTIFICATION CONFIGURATION ====================
from pywebpush import webpush, WebPushException

# Load VAPID keys from environment variables
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_EMAIL = os.getenv("VAPID_EMAIL", "mailto:notifications@mfanobora.co.ke")

# Check if VAPID keys are configured
PUSH_NOTIFICATIONS_ENABLED = bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)

if not PUSH_NOTIFICATIONS_ENABLED:
    print("âš ï¸ Push notifications disabled: VAPID keys not configured")
    print("   Run python generate_vapid_keys.py to generate keys")
    print("   Then add them to .env file")

# In-memory status cache for tracking changes
user_status_cache = {}

def get_stored_status(user_id: int) -> Optional[str]:
    """Get previously stored status from cache"""
    return user_status_cache.get(user_id)

def store_status(user_id: int, status: str):
    """Store current status"""
    user_status_cache[user_id] = status

def send_push_notification(user_id: int, title: str, body: str, url: str = "/dashboard.html"):
    """Send push notification to a specific user"""
    if not PUSH_NOTIFICATIONS_ENABLED:
        print(f"âš ï¸ Push notification not sent (disabled): {title}")
        return False
    
    db = next(get_db_local())
    
    # Get user's push subscriptions
    subscriptions = db.query(PushSubscription).filter(
        PushSubscription.user_id == user_id
    ).all()
    
    if not subscriptions:
        print(f"ðŸ“± No push subscriptions found for user {user_id}")
        db.close()
        return False
    
    notification_data = {
        "title": title,
        "body": body,
        "url": url
    }
    
    success_count = 0
    for sub in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {
                        "p256dh": sub.p256dh,
                        "auth": sub.auth
                    }
                },
                data=json.dumps(notification_data),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={
                    "sub": VAPID_EMAIL,
                }
            )
            success_count += 1
            print(f"âœ… Push notification sent to user {user_id}")
        except WebPushException as e:
            if e.response and e.response.status_code == 410:
                # Subscription expired, remove it
                db.delete(sub)
                db.commit()
                print(f"âŒ Subscription expired for user {user_id}, removed")
            else:
                print(f"âŒ Push notification failed: {e}")
    
    db.commit()
    db.close()
    return success_count > 0

def notify_status_change(user_id: int, old_status: str, new_status: str):
    """Send notification based on status change"""
    notifications_map = {
        'interview_scheduled': (
            'ðŸ“… Interview Scheduled',
            'Your interview has been scheduled! Check your dashboard for details.'
        ),
        'interview_completed': (
            'âœ… Interview Completed',
            'Your interview is complete. Next step: Contract preparation.'
        ),
        'contract_pending': (
            'ðŸ“ Contract Ready',
            'Your contract is ready for signing! Please review and sign.'
        ),
        'placed': (
            'ðŸŽ‰ Placement Confirmed!',
            'Congratulations! Your attachment has been confirmed. Welcome to Mfano Bora Africa Ltd!'
        ),
        'form_completed': (
            'âœ… Application Submitted',
            'Your application has been submitted successfully!'
        )
    }
    notifications_map = {
        'form_completed': (
            'Application Submitted',
            'Your application has been submitted successfully!'
        ),
        'application_approved': (
            'Application Approved',
            'Your application has been approved. The next step is interview scheduling.'
        ),
        'interview_scheduled': (
            'Interview Scheduled',
            'Your interview has been scheduled! Check your dashboard for details.'
        ),
        'interview_completed': (
            'Interview Completed',
            'Your interview is complete. Next step: Contract preparation.'
        ),
        'contract_form_pending': (
            'Contract Form Ready',
            'Your contract form is ready. Please fill and submit it to continue.'
        ),
        'contract_filled': (
            'Contract Submitted',
            'Your contract has been submitted successfully and is awaiting review.'
        ),
        'followup_interview_scheduled': (
            'Follow-up Interview Scheduled',
            'A follow-up interview has been scheduled before your contract is approved.'
        ),
        'followup_interview_completed': (
            'Follow-up Interview Completed',
            'Your follow-up interview is complete. Your contract can now move to approval.'
        ),
        'contract_pending': (
            'Contract Under Review',
            'Your contract is under approval. You will be notified once it is approved.'
        ),
        'placed': (
            'Placement Confirmed!',
            'Congratulations! Your attachment has been confirmed. Welcome to Mfano Bora Africa Ltd!'
        )
    }

    if new_status in notifications_map:
        title, message = notifications_map[new_status]
        send_push_notification(user_id, title, message)

def check_and_notify_status_change(user_id: int, db: Session):
    """Check if status changed and send notification if needed"""
    from main import get_attachee_status  # Import here to avoid circular import
    
    # Get current status
    current_status_data = get_attachee_status(user_id, db)
    current_step = current_status_data.get('current_step', 'registration_complete')
    
    # Get previously stored status
    previous_status = get_stored_status(user_id)
    
    if previous_status and previous_status != current_step:
        # Status changed - send notification
        print(f"ðŸ“¢ Status changed for user {user_id}: {previous_status} -> {current_step}")
        notify_status_change(user_id, previous_status, current_step)
    
    # Store new status
    store_status(user_id, current_step)
    
    return current_step

# Helper function to get user_id from request (for push subscriptions)
def get_user_id_from_request(request: FastAPIRequest) -> Optional[int]:
    """Extract user_id from request (simplified - in production use JWT/session)"""
    # For now, get from query param or body
    return None

# Add these headers to help with camera access (already have this)
@app.middleware("http")
async def add_security_headers(request: FastAPIRequest, call_next):
    response = await call_next(request)
    response.headers["Permissions-Policy"] = "camera=(self)"
    response.headers["Feature-Policy"] = "camera 'self'"
    response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    return response

# ==================== WEB INTERFACE STATIC FILES ====================
# Mount web interface files
web_dir = Path(__file__).parent / "web_interface"
if web_dir.exists():
    app.mount("/css", StaticFiles(directory=str(web_dir / "css")), name="css")
    app.mount("/js", StaticFiles(directory=str(web_dir / "js")), name="js")
    app.mount("/assets", StaticFiles(directory=str(web_dir / "assets")), name="assets")
    
    # Serve HTML pages
    @app.get("/", response_class=HTMLResponse)
    async def serve_login():
        return FileResponse(str(web_dir / "index.html"))
    
    @app.get("/dashboard.html", response_class=HTMLResponse)
    async def serve_dashboard():
        return FileResponse(str(web_dir / "dashboard.html"))
    
    @app.get("/application-form.html", response_class=HTMLResponse)
    async def serve_application_form():
        return FileResponse(str(web_dir / "application-form.html"))
    
    @app.get("/profile.html", response_class=HTMLResponse)
    async def serve_profile():
        return FileResponse(str(web_dir / "profile.html"))
    
    @app.get("/logbook.html", response_class=HTMLResponse)
    async def serve_logbook():
        return FileResponse(str(web_dir / "logbook.html"))
    @app.get("/placement_letter.html", response_class=HTMLResponse)
    async def serve_logbook():
        return FileResponse(str(web_dir / "placement_letter.html"))
    
    @app.get("/attendance.html", response_class=HTMLResponse)
    async def serve_attendance():
        return FileResponse(str(web_dir / "attendance.html"))
    
    @app.get("/requests.html", response_class=HTMLResponse)
    async def serve_requests():
        return FileResponse(str(web_dir / "requests.html"))
    
    @app.get("/tasks.html", response_class=HTMLResponse)
    async def serve_tasks():
        return FileResponse(str(web_dir / "tasks.html"))
    
    @app.get("/reports.html", response_class=HTMLResponse)
    async def serve_reports():
        return FileResponse(str(web_dir / "reports.html"))

    @app.get("/training.html", response_class=HTMLResponse)
    async def serve_training():
        return FileResponse(str(web_dir / "training.html"))

    @app.get("/trainings.html", response_class=HTMLResponse)
    async def serve_trainings():
        return FileResponse(str(web_dir / "training.html"))

    @app.get("/coordinator-dashboard.html", response_class=HTMLResponse)
    async def serve_coordinator_dashboard():
        return FileResponse(str(web_dir / "coordinator-dashboard.html"))

    @app.get("/suggestions.html", response_class=HTMLResponse)
    async def serve_suggestions():
        return FileResponse(str(web_dir / "suggestions.html"))

    @app.get("/challenges.html", response_class=HTMLResponse)
    async def serve_challenges():
        return FileResponse(str(web_dir / "challenges.html"))

    @app.get("/it-manager-dashboard.html", response_class=HTMLResponse)
    async def serve_reports():
        return FileResponse(str(web_dir / "it-manager-dashboard.html"))

    @app.get("/it-manager-users.html", response_class=HTMLResponse)
    async def serve_reports():
        return FileResponse(str(web_dir / "it-manager-users.html"))

    @app.get("/it-manager-settings.html", response_class=HTMLResponse)
    async def serve_reports():
        return FileResponse(str(web_dir / "it-manager-settings.html"))

    @app.get("/it-manager-system-logs.html", response_class=HTMLResponse)
    async def serve_reports():
        return FileResponse(str(web_dir / "it-manager-system-logs.html"))

    @app.get("/it-manager-backup.html", response_class=HTMLResponse)
    async def serve_reports():
        return FileResponse(str(web_dir / "it-manager-backup.html"))
    
    @app.get("/notifications.html", response_class=HTMLResponse)
    async def serve_notifications():
        return FileResponse(str(web_dir / "notifications.html"))
    
    @app.get("/it-manager-disable-requests.html", response_class=HTMLResponse)
    async def serve_it_manager_disable_requests():
        return FileResponse(str(web_dir / "it-manager-disable-requests.html"))
    
    @app.get("/it-manager-attendance-issues.html", response_class=HTMLResponse)
    async def serve_it_manager_attendance_issues():
        return FileResponse(str(web_dir / "it-manager-attendance-issues.html"))

    @app.get("/change-password.html", response_class=HTMLResponse)
    async def serve_change_password():
        change_password_path = web_dir / "change-password.html"
        if change_password_path.exists():
            return FileResponse(str(change_password_path))
        return HTMLResponse(content="<h1>Change Password page not found</h1>", status_code=404)
    
    # Serve service worker
    @app.get("/sw.js", response_class=HTMLResponse)
    async def serve_sw():
        sw_path = web_dir / "sw.js"
        if sw_path.exists():
            return FileResponse(str(sw_path))
        return Response("", status_code=404)

# ==================== PUSH NOTIFICATION ENDPOINTS ====================

@app.get("/api/push/vapid-public-key")
async def get_vapid_public_key():
    """Get VAPID public key for web push subscription"""
    return {"public_key": VAPID_PUBLIC_KEY}

@app.post("/api/push/subscribe")
async def subscribe_to_push(request: FastAPIRequest, db: Session = Depends(get_db_local)):
    """Store push subscription for a user"""
    try:
        data = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    user_id = data.get('user_id')
    endpoint = data.get('endpoint')
    keys = data.get('keys', {})
    
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    if not endpoint:
        raise HTTPException(status_code=400, detail="endpoint required")
    if not keys.get('p256dh') or not keys.get('auth'):
        raise HTTPException(status_code=400, detail="Invalid subscription keys")
    
    # Check if user exists
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if subscription exists
    existing = db.query(PushSubscription).filter(
        PushSubscription.endpoint == endpoint
    ).first()
    
    if existing:
        existing.p256dh = keys['p256dh']
        existing.auth = keys['auth']
        existing.updated_at = datetime.now()
    else:
        subscription = PushSubscription(
            user_id=user_id,
            endpoint=endpoint,
            p256dh=keys['p256dh'],
            auth=keys['auth']
        )
        db.add(subscription)
    
    db.commit()
    
    # Send welcome notification
    send_push_notification(user_id, "ðŸ”” Notifications Enabled", "You will now receive real-time updates about your application status.")
    
    return {"message": "Subscribed successfully"}

@app.delete("/api/push/unsubscribe")
async def unsubscribe_from_push(request: FastAPIRequest, db: Session = Depends(get_db_local)):
    """Remove push subscription"""
    try:
        data = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    endpoint = data.get('endpoint')
    
    if not endpoint:
        raise HTTPException(status_code=400, detail="endpoint required")
    
    subscription = db.query(PushSubscription).filter(
        PushSubscription.endpoint == endpoint
    ).first()
    
    if subscription:
        db.delete(subscription)
        db.commit()
    
    return {"message": "Unsubscribed successfully"}

# ==================== WEB AUTHENTICATION ENDPOINTS ====================

@app.post("/api/auth/start-new")
def start_new_application(db: Session = Depends(get_db_local)):
    """Generate new Student ID for first-time user (Web Interface)"""
    
    # Generate unique Student ID
    last_student = db.query(User).filter(User.role == "attachee").order_by(User.id.desc()).first()
    next_id = (last_student.id + 1) if last_student else 1
    student_id = f"MFB{next_id:06d}"
    
    # Check if student ID already exists
    existing = db.query(User).filter(User.username == student_id).first()
    if existing:
        student_id = f"MFB{next_id + 1:06d}"
    
    # Create user with NO email (NULL)
    new_user = User(
        username=student_id,
        email=None,
        full_name="",
        role="attachee",
        is_active=True,
        phone="",
        hashed_password=None,
        password_set=False,
        first_login=True
    )
    db.add(new_user)
    db.flush()
    
    # Create empty profile
    profile = AttacheeProfile(
        user_id=new_user.id,
        student_id=student_id,
        course="",
        institution="",
        year_of_study=1,
        placement_status="registration_complete"
    )
    db.add(profile)
    
    # Create application form record
    application_form = ApplicationForm(
        attachee_id=new_user.id,
        payment_status="pending",
        status="pending",
        session_start=datetime.now(),
        session_expiry=datetime.now() + timedelta(days=7)
    )
    db.add(application_form)
    
    db.commit()
    
    return {
        "student_id": student_id,
        "user_id": new_user.id,
        "needs_password": True
    }
    
@app.post("/api/auth/check-student")
def check_student(data: dict, db: Session = Depends(get_db_local)):
    """Check if student exists and needs password setup (Web Interface)"""
    student_id = data.get('student_id')
    
    if not student_id:
        raise HTTPException(status_code=400, detail="Student ID required")
    
    user = db.query(User).filter(User.username == student_id).first()
    
    if not user:
        return {"exists": False}
    
    # Check if user has a password set
    has_password = user.hashed_password is not None and user.hashed_password != ""
    
    return {
        "exists": True,
        "user_id": user.id,
        "needs_password_setup": not has_password,
        "has_application": bool(user.application_forms)
    }

@app.post("/api/auth/setup-password")
def setup_password(data: dict, db: Session = Depends(get_db_local)):
    """First-time password setup (Web Interface)"""
    student_id = data.get('student_id')
    password = data.get('password')
    
    if not student_id or not password:
        raise HTTPException(status_code=400, detail="Student ID and password required")
    
    user = db.query(User).filter(User.username == student_id, User.role == "attachee").first()
    if not user:
        raise HTTPException(status_code=404, detail="Student not found")
    
    # Check if password already set
    if user.hashed_password and user.hashed_password != "":
        raise HTTPException(status_code=400, detail="Password already set")
    
    # Set the password
    user.set_password(password)
    
    db.commit()
    
    return {
        "message": "Password set successfully",
        "user_id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role
    }

# ==================== LOGIN ATTEMPT LOGGING ENDPOINTS ====================

@app.get("/api/get-ip")
async def get_client_ip(request: FastAPIRequest):
    """Get client IP address"""
    client_ip = request.client.host if request.client else "unknown"
    # Check for proxy headers
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    return {"ip": client_ip}


@app.post("/api/log-login-attempt")
async def log_login_attempt(
    data: dict,
    request: FastAPIRequest,
    db: Session = Depends(get_db_local)
):
    """Log login attempt from web interface"""
    
    username = data.get('username')
    success = data.get('success', False)
    reason = data.get('reason', '')
    client_ip = data.get('ip') or request.client.host if request.client else "unknown"
    timestamp = data.get('timestamp', datetime.now().isoformat())
    
    # Get user info if exists
    user = db.query(User).filter(User.username == username).first()
    user_id = user.id if user else None
    user_role = user.role if user else None
    
    # Create log entry
    log_entry = SystemLog(
        user_id=user_id,
        action="LOGIN_ATTEMPT",
        details=f"Login {'successful' if success else 'failed'} for user {username}" + (f" - {reason}" if reason else ""),
        ip_address=client_ip,
        log_type="login",
        created_at=datetime.fromisoformat(timestamp.replace('Z', '+00:00')) if timestamp else datetime.now()
    )
    db.add(log_entry)
    
    # Track failed attempts from this IP
    if not success:
        # Count recent failures from this IP
        one_hour_ago = datetime.now() - timedelta(hours=1)
        failed_count = db.query(SystemLog).filter(
            SystemLog.ip_address == client_ip,
            SystemLog.action == "LOGIN_ATTEMPT",
            SystemLog.details.like("%failed%"),
            SystemLog.created_at >= one_hour_ago
        ).count()
        
        # If too many failures, log as security alert
        if failed_count >= 5:
            security_log = SystemLog(
                user_id=None,
                action="SECURITY_ALERT",
                details=f"Multiple failed login attempts from IP {client_ip} - {failed_count} attempts in last hour",
                ip_address=client_ip,
                log_type="security",
                created_at=datetime.now()
            )
            db.add(security_log)
    
    db.commit()
    
    return {"message": "Login attempt logged"}


# Also update the existing login endpoint to log attempts
@app.post("/api/auth/login-web")
def login_web(data: dict, request: FastAPIRequest, db: Session = Depends(get_db_local)):
    """Web interface login endpoint with logging and account status check"""
    username = data.get('username')
    password = data.get('password')
    client_ip = request.client.host if request.client else "unknown"
    
    if not username or not password:
        # Log failed attempt
        log_entry = SystemLog(
            user_id=None,
            action="LOGIN_ATTEMPT",
            details=f"Login failed for {username} - missing credentials",
            ip_address=client_ip,
            log_type="login",
            created_at=datetime.now()
        )
        db.add(log_entry)
        db.commit()
        raise HTTPException(status_code=400, detail="Username and password required")
    
    user = db.query(User).filter(User.username == username).first()
    
    if not user:
        # Log failed attempt - user not found
        log_entry = SystemLog(
            user_id=None,
            action="LOGIN_ATTEMPT",
            details=f"Login failed for {username} - user not found",
            ip_address=client_ip,
            log_type="login",
            created_at=datetime.now()
        )
        db.add(log_entry)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    # Check if password is set
    if not user.hashed_password or user.hashed_password == "":
        log_entry = SystemLog(
            user_id=user.id,
            action="LOGIN_ATTEMPT",
            details=f"Login failed for {username} - password not set",
            ip_address=client_ip,
            log_type="login",
            created_at=datetime.now()
        )
        db.add(log_entry)
        db.commit()
        raise HTTPException(status_code=401, detail="Password not set. Please use 'New Student' option first.")
    
    # Verify password
    if not user.verify_password(password):
        # Log failed attempt
        log_entry = SystemLog(
            user_id=user.id,
            action="LOGIN_ATTEMPT",
            details=f"Login failed for {username} - invalid password",
            ip_address=client_ip,
            log_type="login",
            created_at=datetime.now()
        )
        db.add(log_entry)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    # ========== NEW: Check for auto-disabled account ==========
    # Check if account was auto-disabled due to unpaid fees
    if user.account_auto_disabled_at:
        # Get contract for details
        contract = db.query(Contract).filter(
            Contract.attachee_id == user.id,
            Contract.status == "approved"
        ).order_by(Contract.created_at.desc()).first()
        
        log_entry = SystemLog(
            user_id=user.id,
            action="LOGIN_ATTEMPT",
            details=f"Login failed for {username} - account auto-disabled due to unpaid fees",
            ip_address=client_ip,
            log_type="login",
            created_at=datetime.now()
        )
        db.add(log_entry)
        db.commit()
        
        if contract:
            mode = getattr(contract, 'mode', 'physical')
            total_fee = float(getattr(contract, 'total_fee', 4950 if mode == 'online' else 2950))
            amount_paid = float(getattr(contract, 'amount_paid', 0))
            remaining_balance = total_fee - amount_paid
            
            raise HTTPException(
                status_code=403, 
                detail=f"Account disabled. Payment deadline exceeded. Remaining balance: KES {remaining_balance:,.2f}. Please contact coordinator to request extension."
            )
        else:
            raise HTTPException(
                status_code=403, 
                detail="Account disabled due to unpaid fees. Please contact coordinator."
            )
    
    if not user.is_active:
        log_entry = SystemLog(
            user_id=user.id,
            action="LOGIN_ATTEMPT",
            details=f"Login failed for {username} - account disabled by administrator",
            ip_address=client_ip,
            log_type="login",
            created_at=datetime.now()
        )
        db.add(log_entry)
        db.commit()
        raise HTTPException(status_code=401, detail="Account is deactivated. Please contact administrator.")

    # Enforce payment deadline block directly at login for web students
    try:
        contract_details = get_contract_payment_details(user.id, db)
    except Exception:
        contract_details = None

    if contract_details and contract_details.get("supervisor_approved_at"):
        if not user.contract_approved_at:
            user.contract_approved_at = contract_details["supervisor_approved_at"]

        remaining_balance = contract_details.get("remaining_balance", 0)
        deadline_date = user.payment_deadline_extended_to or (
            user.contract_approved_at + timedelta(days=user.payment_deadline_days)
            if user.contract_approved_at else None
        )

        if deadline_date and remaining_balance > 0 and datetime.now() > deadline_date:
            user.is_active = False
            user.account_auto_disabled_at = datetime.now()
            user.account_auto_disabled_reason = (
                f"Payment deadline exceeded. KES {remaining_balance:,.2f} still pending after "
                f"{user.payment_deadline_days} days."
            )
            db.commit()

            log_entry = SystemLog(
                user_id=user.id,
                action="LOGIN_ATTEMPT",
                details=f"Login failed for {username} - payment deadline exceeded",
                ip_address=client_ip,
                log_type="login",
                created_at=datetime.now()
            )
            db.add(log_entry)
            db.commit()

            raise HTTPException(
                status_code=403,
                detail=f"Account disabled. Payment deadline exceeded. Remaining balance: KES {remaining_balance:,.2f}. Please contact coordinator to request extension."
            )
    # ========== END NEW ==========
    
    # Log successful login
    log_entry = SystemLog(
        user_id=user.id,
        action="LOGIN_ATTEMPT",
        details=f"Login successful for {username}",
        ip_address=client_ip,
        log_type="login",
        created_at=datetime.now()
    )
    db.add(log_entry)
    db.commit()
    
    # Update user's last login info
    user.last_login_ip = client_ip
    user.last_login_at = datetime.now()
    db.commit()
    
    # Get application form status
    app_form = db.query(ApplicationForm).filter(
        ApplicationForm.attachee_id == user.id,
        ApplicationForm.status == "completed"
    ).first()
    
    return {
        "success": True,
        "user_id": user.id,
        "username": user.username,
        "full_name": user.full_name or user.username,
        "role": user.role,
        "email": user.email,
        "phone": user.phone,
        "has_application": app_form is not None,
        "password_set": user.password_set if hasattr(user, 'password_set') else True,
        "needs_password_change": not (user.password_set if hasattr(user, 'password_set') else True)
    }

@app.post("/api/auth/request-password-reset")
def request_password_reset(
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Student requests password reset from coordinator"""
    
    student_id = data.get('student_id')
    
    if not student_id:
        raise HTTPException(status_code=400, detail="Student ID required")
    
    user = db.query(User).filter(User.username == student_id, User.role == "attachee").first()
    if not user:
        raise HTTPException(status_code=404, detail="Student not found")
    
    # Check if there's already a pending reset request
    existing_request = db.query(PasswordResetRequest).filter(
        PasswordResetRequest.user_id == user.id,
        PasswordResetRequest.status == "pending"
    ).first()
    
    if existing_request:
        raise HTTPException(status_code=400, detail="You already have a pending password reset request")
    
    # Create password reset request
    reset_request = PasswordResetRequest(
        user_id=user.id,
        student_id=student_id,
        student_name=user.full_name or user.username,
        status="pending",
        requested_at=datetime.now()
    )
    db.add(reset_request)
    db.commit()
    db.refresh(reset_request)
    
    # Notify all coordinators
    coordinators = db.query(User).filter(User.role == "coordinator").all()
    for coord in coordinators:
        background_tasks.add_task(
            send_push_notification,
            coord.id,
            "ðŸ” Password Reset Request",
            f"Student {user.full_name or user.username} ({student_id}) has requested a password reset"
        )
        
        notification = Notification(
            user_id=coord.id,
            title="Password Reset Request",
            message=f"Student {user.full_name or user.username} ({student_id}) requests password reset",
            type="password_reset_request"
        )
        db.add(notification)

    db.commit()
    
    return {
        "message": "Password reset request sent to coordinator",
        "request_id": reset_request.id
    }

@app.get("/api/debug/routes")
def debug_routes():
    """List all registered routes for debugging"""
    routes = []
    for route in app.routes:
        routes.append({
            "path": route.path,
            "methods": list(route.methods) if hasattr(route, 'methods') else []
        })
    return {"routes": routes}

@app.get("/notification.wav")
async def get_notification_sound():
    """Serve notification sound file"""
    sound_path = Path(__file__).parent / "web_interface" / "notification.wav"
    if sound_path.exists():
        return FileResponse(sound_path, media_type="audio/wav")
    return Response(status_code=404)

# ==================== WEB ATTENDANCE ENDPOINTS ====================

@app.get("/api/attachee/attendance/today/{user_id}")
def get_today_attendance(user_id: int, db: Session = Depends(get_db_local)):
    """Get today's attendance status (Web Interface)"""
    today = date.today()
    
    attendance = db.query(Attendance).filter(
        Attendance.attachee_id == user_id,
        Attendance.date == today
    ).first()
    
    # Debug logging
    print(f"ðŸ“Š Fetching attendance for user {user_id} on {today}")
    if attendance:
        print(f"   Record found - ID: {attendance.id}")
        print(f"   check_in_time: {attendance.check_in_time}")
        print(f"   check_out_time: {attendance.check_out_time}")
        print(f"   status: {attendance.status}")
    else:
        print(f"   No attendance record found")
    
    return {
        "has_record": attendance is not None,
        "checked_in": attendance.check_in_time is not None if attendance else False,
        "checked_out": attendance.check_out_time is not None if attendance else False,
        "check_in_time": attendance.check_in_time.strftime("%H:%M:%S") if attendance and attendance.check_in_time else None,
        "check_out_time": attendance.check_out_time.strftime("%H:%M:%S") if attendance and attendance.check_out_time else None,
        "status": attendance.status if attendance else "not_started"
    }

# ==================== WEB TASKS ENDPOINTS ====================

@app.get("/api/attachee/tasks/summary/{user_id}")
def get_tasks_summary(user_id: int, db: Session = Depends(get_db_local)):
    """Get tasks summary counts (Web Interface)"""
    pending_count = db.query(Task).filter(
        Task.assigned_to_id == user_id,
        Task.status == "pending"
    ).count()
    
    completed_count = db.query(Task).filter(
        Task.assigned_to_id == user_id,
        Task.status == "completed"
    ).count()
    
    return {
        "pending": pending_count,
        "completed": completed_count,
        "total": pending_count + completed_count
    }

# ==================== WEB REPORTS ENDPOINTS ====================

def _public_upload_url(file_path: str) -> str:
    """Convert a stored filesystem path into a browser-accessible uploads URL."""
    if not file_path:
        return file_path

    normalized = str(file_path).replace("\\", "/")
    if normalized.startswith("/uploads/"):
        return normalized
    if normalized.startswith("uploads/"):
        return f"/{normalized}"

    try:
        path_obj = Path(file_path).resolve()
        uploads_root = Path(Config.UPLOAD_DIR).resolve()
        relative_path = path_obj.relative_to(uploads_root).as_posix()
        return f"/uploads/{relative_path}"
    except Exception:
        return f"/uploads/{Path(file_path).name}"


@app.post("/api/upload/report-web/{user_id}")
async def upload_report_web(
    user_id: int,
    report_type: str = Form(...),
    title: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db_local)
):
    """Upload report file (Web Interface)"""
    if not file.filename.endswith(('.pdf', '.doc', '.docx')):
        raise HTTPException(status_code=400, detail="Only PDF and Word documents are allowed")
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_filename = f"report_{user_id}_{timestamp}.pdf"
    file_path = Config.UPLOAD_DIR / safe_filename
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    report = Report(
        attachee_id=user_id,
        report_type=report_type,
        title=title,
        file_url=_public_upload_url(str(file_path))
    )
    db.add(report)
    db.commit()
    
    return {"message": "Report uploaded", "report_id": report.id, "file_url": _public_upload_url(str(file_path))}

# ==================== HEALTH CHECK ====================

@app.get("/health")
def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/api/server/info")
def server_info():
    return {
        "ip": Config.get_local_ip(),
        "port": 8000,
        "name": "Mfano Bora Server",
        "push_notifications_enabled": PUSH_NOTIFICATIONS_ENABLED
    }

# ==================== AUTHENTICATION ENDPOINTS (Desktop) ====================

@app.post("/api/auth/login")
def login(username: str, password: str, db: Session = Depends(get_db_local)):
    """Authenticate user (Desktop Client)"""
    user = db.query(User).filter(User.username == username).first()
    
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    if not user.verify_password(password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    if not user.is_active:
        raise HTTPException(status_code=401, detail="Account is deactivated")
    
    return {
        "success": True,
        "user_id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "email": user.email,
        "phone": user.phone
    }

@app.post("/api/auth/register")
def register(user_data: dict, db: Session = Depends(get_db_local)):
    """Register a new attachee (Desktop Client)"""
    existing_user = db.query(User).filter(
        (User.username == user_data.get('username'))
    ).first()
    
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    new_user = User(
        username=user_data.get('username'),
        email="",
        full_name="",
        role="attachee",
        phone="",
        is_active=True
    )
    new_user.set_password(user_data.get('password'))
    db.add(new_user)
    db.flush()
    
    profile = AttacheeProfile(
        user_id=new_user.id,
        student_id="",
        course="",
        institution="",
        year_of_study=1,
        placement_status="not_applied"
    )
    db.add(profile)
    
    application_form = ApplicationForm(
        attachee_id=new_user.id,
        payment_status="pending",
        status="pending",
        session_start=datetime.now(),
        session_expiry=datetime.now() + timedelta(days=7)
    )
    db.add(application_form)
    
    db.commit()
    
    return {
        "success": True,
        "user_id": new_user.id,
        "username": new_user.username,
        "message": "Registration successful. Please login to complete your application."
    }

@app.get("/api/auth/check-username/{username}")
def check_username(username: str, db: Session = Depends(get_db_local)):
    """Check if username is available"""
    user = db.query(User).filter(User.username == username).first()
    return {"available": user is None}

# ==================== ATTACHEE DASHBOARD ====================

@app.get("/api/attachee/dashboard/{user_id}")
def get_attachee_dashboard(user_id: int, db: Session = Depends(get_db_local)):
    """Get attachee dashboard data"""
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == user_id).first()
    
    logbook_count = db.query(LogbookEntry).filter(
        LogbookEntry.attachee_id == user_id
    ).count()
    
    attendance_count = db.query(Attendance).filter(
        Attendance.attachee_id == user_id
    ).count()
    
    pending_requests = db.query(LeaveRequest).filter(
        LeaveRequest.attachee_id == user_id,
        LeaveRequest.status == "forwarded"
    ).count()
    
    pending_tasks = db.query(Task).filter(
        Task.assigned_to_id == user_id,
        Task.status == "pending"
    ).count()
    
    recent_logbooks = db.query(LogbookEntry).filter(
        LogbookEntry.attachee_id == user_id
    ).order_by(LogbookEntry.entry_date.desc()).limit(5).all()
    
    return {
        "profile": {
            "student_id": profile.student_id if profile else None,
            "course": profile.course if profile else None,
            "placement_status": profile.placement_status if profile else None,
            "department": profile.department if profile else None
        },
        "stats": {
            "logbook_entries": logbook_count,
            "attendance_days": attendance_count,
            "pending_requests": pending_requests,
            "pending_tasks": pending_tasks
        },
        "recent_logbooks": [
            {
                "id": l.id, 
                "title": l.title, 
                "entry_date": l.entry_date.isoformat(), 
                "submitted": l.submitted
            }
            for l in recent_logbooks
        ]
    }

# ==================== ATTACHEE LOGBOOK ====================

@app.post("/api/attachee/logbook")
async def create_logbook_entry(
    request: FastAPIRequest,  # Use FastAPIRequest (not Request)
    db: Session = Depends(get_db_local)
):
    """Create a logbook entry (supports JSON body from frontend)"""
    try:
        data = await request.json()
    except Exception as e:
        print(f"Error parsing JSON: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON data")
    
    # Get data from JSON body
    user_id = data.get('user_id')
    title = data.get('title')
    description = data.get('description')
    entry_date = data.get('entry_date')
    tasks_completed = data.get('tasks_completed')
    challenges = data.get('challenges')
    
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    if not description:
        raise HTTPException(status_code=400, detail="description is required")
    if not entry_date:
        raise HTTPException(status_code=400, detail="entry_date is required")
    
    # Check if user exists
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if attachee is placed (can only create logbook if placed)
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == user_id).first()
    if profile and profile.placement_status != "placed":
        raise HTTPException(status_code=403, detail="You can only create logbook entries after your placement is confirmed")
    
    # Auto-fetch tasks completed if not manually provided
    if not tasks_completed:
        tasks_completed = get_completed_tasks_for_date(user_id, entry_date, db)
    
    entry = LogbookEntry(
        attachee_id=user_id,
        title=title,
        description=description,
        entry_date=date.fromisoformat(entry_date),
        tasks_completed=tasks_completed,
        challenges=challenges
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    
    return {"message": "Logbook entry created", "entry_id": entry.id}


@app.post("/api/attachee/logbook/create")
async def create_logbook_entry_alt(
    request: FastAPIRequest,  # Use FastAPIRequest here too
    db: Session = Depends(get_db_local)
):
    """Alternative endpoint for logbook creation with JSON body"""
    try:
        data = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid JSON data")
    
    user_id = data.get('user_id')
    title = data.get('title')
    description = data.get('description')
    entry_date = data.get('entry_date')
    tasks_completed = data.get('tasks_completed')
    challenges = data.get('challenges')
    
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    if not description:
        raise HTTPException(status_code=400, detail="description is required")
    if not entry_date:
        raise HTTPException(status_code=400, detail="entry_date is required")
    
    # Check if user exists
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if attachee is placed (can only create logbook if placed)
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == user_id).first()
    if profile and profile.placement_status != "placed":
        raise HTTPException(status_code=403, detail="You can only create logbook entries after your placement is confirmed")
    
    # Auto-fetch tasks completed if not manually provided
    if not tasks_completed:
        tasks_completed = get_completed_tasks_for_date(user_id, entry_date, db)
    
    entry = LogbookEntry(
        attachee_id=user_id,
        title=title,
        description=description,
        entry_date=date.fromisoformat(entry_date),
        tasks_completed=tasks_completed,
        challenges=challenges
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    
    return {"message": "Logbook entry created", "entry_id": entry.id}


def get_completed_tasks_for_date(user_id: int, entry_date: str, db: Session) -> str:
    """Fetch completed tasks for a specific date and format them as a string"""
    try:
        target_date = date.fromisoformat(entry_date)
        
        # Query tasks completed on or before the entry date
        tasks = db.query(Task).filter(
            Task.assigned_to_id == user_id,
            Task.status == "completed",
            Task.completed_at <= datetime.combine(target_date, datetime.max.time())
        ).order_by(Task.completed_at.desc()).all()
        
        if not tasks:
            return "No tasks completed on this date"
        
        # Format tasks as a readable string
        task_list = []
        for task in tasks:
            task_list.append(f"âœ“ {task.title}")
        
        return "\n".join(task_list)
        
    except Exception as e:
        print(f"Error fetching completed tasks: {e}")
        return "Unable to fetch tasks"


@app.get("/api/attachee/logbook/{user_id}")
def get_logbook_entries(
    user_id: int, 
    db: Session = Depends(get_db_local)
):
    """Get all logbook entries for an attachee"""
    # Check if user exists
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    entries = db.query(LogbookEntry).filter(
        LogbookEntry.attachee_id == user_id
    ).order_by(LogbookEntry.entry_date.desc()).all()
    
    return [
        {
            "id": e.id,
            "title": e.title,
            "description": e.description,
            "entry_date": e.entry_date.isoformat(),
            "submitted": e.submitted,
            "feedback": e.feedback,
            "tasks_completed": e.tasks_completed,
            "challenges": e.challenges,
            "submitted_at": e.submitted_at.isoformat() if e.submitted_at else None
        }
        for e in entries
    ]


@app.get("/api/attachee/logbook/{user_id}/tasks-summary")
def get_logbook_tasks_summary(
    user_id: int,
    entry_date: str,
    db: Session = Depends(get_db_local)
):
    """Get summary of completed tasks for a specific date (for frontend preview)"""
    try:
        tasks_completed = get_completed_tasks_for_date(user_id, entry_date, db)
        return {
            "tasks_completed": tasks_completed,
            "has_tasks": tasks_completed != "No tasks completed on this date"
        }
    except Exception as e:
        return {
            "tasks_completed": "Unable to fetch tasks",
            "has_tasks": False,
            "error": str(e)
        }


@app.post("/api/attachee/logbook/{entry_id}/submit")
def submit_logbook_entry(
    entry_id: int, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Submit a logbook entry for review"""
    entry = db.query(LogbookEntry).filter(LogbookEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    
    if entry.submitted:
        raise HTTPException(status_code=400, detail="Entry already submitted")
    
    print(f"ðŸ““ Submitting logbook entry {entry_id} for student {entry.attachee_id}")
    
    entry.submitted = True
    entry.submitted_at = datetime.now()
    db.commit()
    
    # Find supervisor by role (not by assigned_supervisor_id)
    supervisor = db.query(User).filter(User.role == "supervisor").first()
    
    if supervisor:
        print(f"ðŸ“¢ Notifying supervisor: {supervisor.full_name} (ID: {supervisor.id})")
        background_tasks.add_task(
            send_push_notification,
            supervisor.id,
            "ðŸ““ New Logbook Entry",
            f"Attachee has submitted a new logbook entry for review: {entry.title}"
        )
        
        notification = Notification(
            user_id=supervisor.id,
            title="Logbook Entry Submitted",
            message=f"Attachee has submitted '{entry.title}' for review",
            type="logbook_submission"
        )
        db.add(notification)
        db.commit()
    else:
        print("âš ï¸ No supervisor found in the system to notify")
    
    return {"message": "Logbook entry submitted successfully"}


@app.put("/api/attachee/logbook/{entry_id}")
def update_logbook_entry(
    entry_id: int,
    data: dict,
    db: Session = Depends(get_db_local)
):
    """Update a logbook entry (only if not submitted)"""
    entry = db.query(LogbookEntry).filter(LogbookEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    
    if entry.submitted:
        raise HTTPException(status_code=400, detail="Cannot update a submitted entry")
    
    if 'title' in data:
        entry.title = data['title']
    if 'description' in data:
        entry.description = data['description']
    if 'entry_date' in data:
        entry.entry_date = date.fromisoformat(data['entry_date'])
    if 'tasks_completed' in data:
        entry.tasks_completed = data['tasks_completed']
    if 'challenges' in data:
        entry.challenges = data['challenges']
    
    db.commit()
    
    return {"message": "Logbook entry updated successfully"}


@app.delete("/api/attachee/logbook/{entry_id}")
def delete_logbook_entry(
    entry_id: int,
    db: Session = Depends(get_db_local)
):
    """Delete a logbook entry (only if not submitted)"""
    entry = db.query(LogbookEntry).filter(LogbookEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    
    if entry.submitted:
        raise HTTPException(status_code=400, detail="Cannot delete a submitted entry")
    
    db.delete(entry)
    db.commit()
    
    return {"message": "Logbook entry deleted successfully"}


@app.get("/api/supervisor/logbook/{supervisor_id}/pending")
def get_pending_logbooks_for_supervisor(
    supervisor_id: int,
    db: Session = Depends(get_db_local)
):
    """Get pending logbook entries for supervisor's students"""
    # Get all students under this supervisor
    students = db.query(AttacheeProfile).filter(
        AttacheeProfile.assigned_supervisor_id == supervisor_id
    ).all()
    
    student_ids = [s.user_id for s in students]
    
    # Get pending logbook entries
    pending_entries = db.query(LogbookEntry).filter(
        LogbookEntry.attachee_id.in_(student_ids),
        LogbookEntry.submitted == True,
        LogbookEntry.feedback == None
    ).order_by(LogbookEntry.submitted_at.desc()).all()
    
    result = []
    for entry in pending_entries:
        student = db.query(User).filter(User.id == entry.attachee_id).first()
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == entry.attachee_id).first()
        
        result.append({
            "id": entry.id,
            "student_name": student.full_name if student else "Unknown",
            "student_id": profile.student_id if profile else "N/A",
            "title": entry.title,
            "description": entry.description[:200] if entry.description else "",
            "entry_date": entry.entry_date.isoformat(),
            "submitted_at": entry.submitted_at.isoformat() if entry.submitted_at else None,
            "tasks_completed": entry.tasks_completed,
            "challenges": entry.challenges
        })
    
    return result


@app.post("/api/supervisor/logbook/{entry_id}/feedback")
def give_logbook_feedback(
    entry_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Provide feedback on a logbook entry"""
    entry = db.query(LogbookEntry).filter(LogbookEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    
    feedback = data.get('feedback')
    if not feedback:
        raise HTTPException(status_code=400, detail="Feedback is required")
    
    entry.feedback = feedback
    entry.feedback_given_at = datetime.now()
    db.commit()
    
    # Notify student
    background_tasks.add_task(
        send_push_notification,
        entry.attachee_id,
        "ðŸ““ Logbook Feedback",
        f"Your supervisor has provided feedback on your logbook entry: {entry.title}"
    )
    
    notification = Notification(
        user_id=entry.attachee_id,
        title="Logbook Feedback Received",
        message=f"Feedback on '{entry.title}': {feedback[:100]}...",
        type="logbook_feedback"
    )
    db.add(notification)
    db.commit()
    
    return {"message": "Feedback submitted successfully"}

# ==================== ATTACHEE ATTENDANCE ====================

@app.get("/api/attachee/attendance/history/{user_id}")
def get_attendance_history(user_id: int, db: Session = Depends(get_db_local)):
    """Get attendance history for an attachee"""
    records = db.query(Attendance).filter(
        Attendance.attachee_id == user_id
    ).order_by(Attendance.date.desc()).all()
    
    return [
        {
            "id": r.id,
            "date": r.date.isoformat(),
            "check_in_time": r.check_in_time.strftime("%H:%M:%S") if r.check_in_time else None,
            "check_out_time": r.check_out_time.strftime("%H:%M:%S") if r.check_out_time else None,
            "status": r.status,
            "remarks": r.remarks
        }
        for r in records
    ]

@app.post("/api/attachee/attendance/checkin")
def check_in(user_id: int, db: Session = Depends(get_db_local)):
    """Record check-in time"""
    today = date.today()
    
    existing = db.query(Attendance).filter(
        Attendance.attachee_id == user_id,
        Attendance.date == today
    ).first()
    
    if existing and existing.check_in_time:
        return {
            "message": "Already checked in today",
            "already_checked_in": True,
            "time": existing.check_in_time.strftime("%H:%M:%S")
        }
    
    if existing:
        existing.check_in_time = datetime.now().time()
        existing.status = "present"
    else:
        attendance = Attendance(
            attachee_id=user_id,
            date=today,
            check_in_time=datetime.now().time(),
            status="present"
        )
        db.add(attendance)
    
    db.commit()
    
    return {"message": "Checked in successfully", "time": datetime.now().strftime("%H:%M:%S")}

@app.post("/api/attachee/attendance/checkout")
def check_out(user_id: int, db: Session = Depends(get_db_local)):
    """Record check-out time"""
    today = date.today()
    
    attendance = db.query(Attendance).filter(
        Attendance.attachee_id == user_id,
        Attendance.date == today
    ).first()
    
    if not attendance:
        return {
            "message": "No check-in record found for today. Please check in first.",
            "no_checkin": True
        }
    
    if attendance.check_out_time:
        return {
            "message": "Already checked out today",
            "already_checked_out": True,
            "time": attendance.check_out_time.strftime("%H:%M:%S")
        }
    
    attendance.check_out_time = datetime.now().time()
    db.commit()
    
    return {"message": "Checked out successfully", "time": datetime.now().strftime("%H:%M:%S")}

# ==================== ATTACHEE REQUESTS ====================

@app.post("/api/attachee/request")
def create_leave_request(
    user_id: int,
    request_type: str,
    title: str,
    description: str,
    recipient_role: str,
    start_date: str = None,
    end_date: str = None,
    db: Session = Depends(get_db_local)
):
    """Create a new leave request"""
    new_request = LeaveRequest(
        attachee_id=user_id,
        request_type=request_type,
        title=title,
        description=description,
        recipient_role=recipient_role,
        start_date=date.fromisoformat(start_date) if start_date else None,
        end_date=date.fromisoformat(end_date) if end_date else None
    )
    db.add(new_request)
    db.commit()
    db.refresh(new_request)

    if recipient_role == "coordinator":
        coordinator = db.query(User).filter(User.role == "coordinator").first()
        if coordinator:
            send_push_notification(
                coordinator.id,
                "New Request",
                f"{title} requires your review"
            )
            db.add(Notification(
                user_id=coordinator.id,
                title="New Request",
                message=f"{title} requires your review",
                type="leave_request"
            ))
            db.commit()
    
    return {"message": "Request submitted", "request_id": new_request.id}

@app.get("/api/attachee/requests/{user_id}")
def get_my_requests(user_id: int, db: Session = Depends(get_db_local)):
    """Get all leave requests by an attachee"""
    requests = db.query(LeaveRequest).filter(
        LeaveRequest.attachee_id == user_id
    ).order_by(LeaveRequest.created_at.desc()).all()
    
    return [
        {
            "id": r.id,
            "type": r.request_type,
            "title": r.title,
            "description": r.description,
            "status": r.status,
            "response": r.response,
            "created_at": r.created_at.isoformat()
        }
        for r in requests
    ]
    # ==================== COORDINATOR LEAVE REQUESTS ENDPOINTS ====================

@app.get("/api/coordinator/leave-requests")
def get_all_leave_requests(db: Session = Depends(get_db_local)):
    """Get all leave requests from all attachees for coordinator view"""
    
    # Get all leave requests with attachee information
    requests = db.query(LeaveRequest).order_by(LeaveRequest.created_at.desc()).all()
    
    result = []
    for req in requests:
        # Get attachee information
        attachee = db.query(User).filter(User.id == req.attachee_id).first()
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == req.attachee_id).first()
        
        result.append({
            "id": req.id,
            "attachee_id": req.attachee_id,
            "student_name": attachee.full_name if attachee else "Unknown",
            "student_id": profile.student_id if profile else "N/A",
            "type": req.request_type,
            "title": req.title,
            "description": req.description,
            "status": req.status,
            "response": req.response,
            "recipient_role": req.recipient_role,
            "start_date": req.start_date.isoformat() if req.start_date else None,
            "end_date": req.end_date.isoformat() if req.end_date else None,
            "created_at": req.created_at.isoformat(),
            "responded_at": req.responded_at.isoformat() if req.responded_at else None
        })
    
    return result


@app.get("/api/coordinator/leave-requests/pending")
def get_pending_leave_requests(db: Session = Depends(get_db_local)):
    """Get only pending leave requests for coordinator"""
    
    requests = db.query(LeaveRequest).filter(
        LeaveRequest.status == "forwarded"
    ).order_by(LeaveRequest.created_at.asc()).all()
    
    result = []
    for req in requests:
        attachee = db.query(User).filter(User.id == req.attachee_id).first()
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == req.attachee_id).first()
        
        result.append({
            "id": req.id,
            "attachee_id": req.attachee_id,
            "student_name": attachee.full_name if attachee else "Unknown",
            "student_id": profile.student_id if profile else "N/A",
            "type": req.request_type,
            "title": req.title,
            "description": req.description,
            "recipient_role": req.recipient_role,
            "start_date": req.start_date.isoformat() if req.start_date else None,
            "end_date": req.end_date.isoformat() if req.end_date else None,
            "created_at": req.created_at.isoformat()
        })
    
    return result


@app.post("/api/coordinator/leave-request/{request_id}/process")
def process_leave_request(
    request_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Coordinator processes a leave request (approve or reject)"""
    
    leave_request = db.query(LeaveRequest).filter(LeaveRequest.id == request_id).first()
    if not leave_request:
        raise HTTPException(status_code=404, detail="Leave request not found")
    
    approved = data.get('approved', False)
    response_message = data.get('response', '')
    
    # Update the request
    leave_request.status = "approved" if approved else "rejected"
    leave_request.response = response_message
    leave_request.responded_at = datetime.now()
    db.commit()
    
    # Send push notification to student
    background_tasks.add_task(
        send_push_notification,
        leave_request.attachee_id,
        "ðŸ“ Leave Request Update",
        f"Your leave request '{leave_request.title}' has been {leave_request.status}. {response_message}"
    )
    
    # Create notification for student
    notification = Notification(
        user_id=leave_request.attachee_id,
        title="Leave Request Update",
        message=f"Your leave request '{leave_request.title}' has been {leave_request.status}. {response_message}",
        type="leave_request"
    )
    db.add(notification)
    db.commit()
    
    return {
        "message": f"Leave request {leave_request.status} successfully",
        "request_id": request_id,
        "status": leave_request.status
    }


@app.get("/api/coordinator/request-history")
def get_coordinator_request_history(db: Session = Depends(get_db_local)):
    """Get all request history items for the coordinator attachee manager."""

    history = []

    # Overtime requests
    overtime_forms = db.query(ApplicationForm).filter(
        ApplicationForm.overtime_requested == True
    ).all()
    for form in overtime_forms:
        student = db.query(User).filter(User.id == form.attachee_id).first()
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == form.attachee_id).first()
        if form.overtime_approved:
            status = "approved"
        elif form.status == "expired":
            status = "expired"
        elif form.status == "in_progress":
            status = "pending"
        else:
            status = form.status or "pending"
        history.append({
            "id": form.id,
            "type": "overtime",
            "title": "Overtime Request",
            "student_name": student.full_name if student else "Unknown",
            "student_id": profile.student_id if profile else "N/A",
            "status": status,
            "requested_at": form.session_start.isoformat() if form.session_start else None,
            "summary": f"{form.overtime_minutes or 10} minute extension requested",
        })

    # Manual attendance requests
    notifications = db.query(Notification).filter(
        Notification.type == "attendance_request"
    ).all()
    for notif in notifications:
        message = notif.message or ""
        student_name = "Unknown"
        student_id = "N/A"
        import re
        id_match = re.search(r'\(([^)]+)\)', message)
        if id_match:
            student_identifier = id_match.group(1)
            profile = db.query(AttacheeProfile).filter(
                AttacheeProfile.student_id == student_identifier
            ).first()
            if profile:
                user = db.query(User).filter(User.id == profile.user_id).first()
                if user:
                    student_name = user.full_name or user.username
                    student_id = student_identifier
            else:
                user = db.query(User).filter(User.username == student_identifier).first()
                if user:
                    student_name = user.full_name or user.username
                    student_id = student_identifier
        action = "checkout" if "checkout" in message.lower() else "checkin"
        history.append({
            "id": notif.id,
            "type": "manual",
            "title": f"Manual {action.capitalize()} Request",
            "student_name": student_name,
            "student_id": student_id,
            "status": "pending" if not notif.is_read else "processed",
            "requested_at": notif.created_at.isoformat() if notif.created_at else None,
            "summary": message,
        })

    # Leave requests
    leave_requests = db.query(LeaveRequest).order_by(LeaveRequest.created_at.desc()).all()
    for req in leave_requests:
        student = db.query(User).filter(User.id == req.attachee_id).first()
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == req.attachee_id).first()
        history.append({
            "id": req.id,
            "type": "leave",
            "title": req.title,
            "student_name": student.full_name if student else "Unknown",
            "student_id": profile.student_id if profile else "N/A",
            "status": req.status,
            "requested_at": req.created_at.isoformat() if req.created_at else None,
            "summary": req.response or req.description or "",
        })

    # Password reset requests
    password_requests = db.query(PasswordResetRequest).order_by(PasswordResetRequest.requested_at.desc()).all()
    for req in password_requests:
        history.append({
            "id": req.id,
            "type": "password",
            "title": "Password Reset Request",
            "student_name": req.student_name,
            "student_id": req.student_id,
            "status": req.status,
            "requested_at": req.requested_at.isoformat() if req.requested_at else None,
            "summary": "Password reset request",
        })

    # Account disable / extension / auto-disable requests
    disable_requests = db.query(DisableRequest).filter(
        DisableRequest.disable_type.in_(["extension_request", "auto_disable"])
    ).order_by(DisableRequest.requested_at.desc()).all()
    for req in disable_requests:
        student = db.query(User).filter(User.id == req.target_user_id).first()
        title = "Account Extension Request" if req.disable_type == "extension_request" else "Account Disable Request"
        summary = req.reason or ""
        if req.disable_type == "auto_disable":
            summary = req.reason or (student.account_auto_disabled_reason if student else "")
        history.append({
            "id": req.id,
            "type": "account_disable",
            "title": title,
            "student_name": student.full_name if student else "Unknown",
            "student_id": student.username if student else "Unknown",
            "status": req.status,
            "requested_at": req.requested_at.isoformat() if req.requested_at else None,
            "summary": summary,
        })

    history.sort(key=lambda item: item.get("requested_at") or "", reverse=True)
    return history


# Optional: Endpoint to get leave requests filtered by status
@app.get("/api/coordinator/leave-requests/status/{status}")
def get_leave_requests_by_status(
    status: str,
    db: Session = Depends(get_db_local)
):
    """Get leave requests filtered by status (pending, approved, rejected)"""
    
    if status not in ["pending", "approved", "rejected"]:
        raise HTTPException(status_code=400, detail="Invalid status. Use: pending, approved, rejected")
    
    requests = db.query(LeaveRequest).filter(
        LeaveRequest.status == status
    ).order_by(LeaveRequest.created_at.desc()).all()
    
    result = []
    for req in requests:
        attachee = db.query(User).filter(User.id == req.attachee_id).first()
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == req.attachee_id).first()
        
        result.append({
            "id": req.id,
            "attachee_id": req.attachee_id,
            "student_name": attachee.full_name if attachee else "Unknown",
            "student_id": profile.student_id if profile else "N/A",
            "type": req.request_type,
            "title": req.title,
            "description": req.description,
            "status": req.status,
            "response": req.response,
            "start_date": req.start_date.isoformat() if req.start_date else None,
            "end_date": req.end_date.isoformat() if req.end_date else None,
            "created_at": req.created_at.isoformat(),
            "responded_at": req.responded_at.isoformat() if req.responded_at else None
        })
    
    return result

@app.post("/api/coordinator/leave-request/{request_id}/forward")
def forward_leave_request_to_supervisor(
    request_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Coordinator forwards leave request to supervisor"""
    
    leave_request = db.query(LeaveRequest).filter(LeaveRequest.id == request_id).first()
    if not leave_request:
        raise HTTPException(status_code=404, detail="Leave request not found")
    
    supervisor_id = data.get('supervisor_id')
    notes = data.get('notes', '')
    
    # If no supervisor_id provided, get the first supervisor
    if not supervisor_id:
        supervisor = db.query(User).filter(User.role == "supervisor").first()
        if not supervisor:
            raise HTTPException(status_code=404, detail="No supervisor found in the system")
        supervisor_id = supervisor.id
    
    # Verify supervisor exists
    supervisor = db.query(User).filter(User.id == supervisor_id, User.role == "supervisor").first()
    if not supervisor:
        raise HTTPException(status_code=404, detail="Supervisor not found")
    
    # Update the request
    leave_request.status = "forwarded"  # Remove from coordinator pending queue
    leave_request.recipient_role = "supervisor"
    leave_request.responded_at = datetime.now()
    if notes:
        leave_request.response = f"Forwarded to supervisor. Notes: {notes}"
    else:
        leave_request.response = "Forwarded to supervisor for approval"
    
    db.commit()
    
    # Send push notification to supervisor
    background_tasks.add_task(
        send_push_notification,
        supervisor_id,
        "ðŸ“ New Leave Request",
        f"New leave request from {leave_request.title} requires your approval"
    )
    
    # Create notification for supervisor
    notification = Notification(
        user_id=supervisor_id,
        title="Leave Request Pending",
        message=f"Leave request '{leave_request.title}' from student requires your approval",
        type="leave_request"
    )
    db.add(notification)
    
    # Notify student that request was forwarded
    background_tasks.add_task(
        send_push_notification,
        leave_request.attachee_id,
        "ðŸ“ Leave Request Forwarded",
        f"Your leave request '{leave_request.title}' has been forwarded to supervisor for approval"
    )
    
    db.commit()
    
    return {
        "message": f"Leave request forwarded to supervisor {supervisor.full_name}",
        "request_id": request_id,
        "supervisor_id": supervisor_id,
        "status": "forwarded"
    }

@app.get("/api/supervisor/leave-requests")
def get_supervisor_leave_requests(
    db: Session = Depends(get_db_local)
):
    """Get leave requests for the supervisor (by role, not by ID)"""
    
    # Get supervisor by role
    supervisor = db.query(User).filter(User.role == "supervisor").first()
    
    if not supervisor:
        print("âš ï¸ No supervisor found in the system")
        return []
    
    print(f"ðŸ” Returning leave requests for supervisor: {supervisor.full_name} (ID: {supervisor.id})")
    
    # Get all requests that are forwarded to supervisor (recipient_role == "supervisor")
    # and status is 'pending' (not yet approved/rejected by supervisor)
    requests_list = db.query(LeaveRequest).filter(
        LeaveRequest.recipient_role == "supervisor",
        LeaveRequest.status == "forwarded"
    ).order_by(LeaveRequest.created_at.desc()).all()
    
    print(f"ðŸ“‹ Found {len(requests_list)} pending leave requests")
    
    result = []
    for req in requests_list:
        attachee = db.query(User).filter(User.id == req.attachee_id).first()
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == req.attachee_id).first()
        
        result.append({
            "id": req.id,
            "attachee_id": req.attachee_id,
            "student_name": attachee.full_name if attachee else "Unknown",
            "student_id": profile.student_id if profile else "N/A",
            "type": req.request_type,
            "title": req.title,
            "description": req.description,
            "status": req.status,
            "response": req.response,
            "start_date": req.start_date.isoformat() if req.start_date else None,
            "end_date": req.end_date.isoformat() if req.end_date else None,
            "created_at": req.created_at.isoformat(),
            "recipient_role": req.recipient_role
        })
    
    return result

@app.get("/api/supervisor/leave-requests/{supervisor_id}")
def get_supervisor_leave_requests(
    supervisor_id: int,
    db: Session = Depends(get_db_local)
):
    """Get leave requests for supervisor (requests forwarded by coordinator)"""
    
    # Get all requests that are:
    # 1. Forwarded to supervisor (recipient_role == "supervisor")
    # 2. Status is 'pending' (not yet approved/rejected by supervisor)
    requests_list = db.query(LeaveRequest).filter(
        LeaveRequest.recipient_role == "supervisor",
        LeaveRequest.status == "forwarded"
    ).order_by(LeaveRequest.created_at.desc()).all()
    
    result = []
    for req in requests_list:
        attachee = db.query(User).filter(User.id == req.attachee_id).first()
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == req.attachee_id).first()
        
        result.append({
            "id": req.id,
            "attachee_id": req.attachee_id,
            "student_name": attachee.full_name if attachee else "Unknown",
            "student_id": profile.student_id if profile else "N/A",
            "type": req.request_type,
            "title": req.title,
            "description": req.description,
            "status": req.status,
            "response": req.response,
            "start_date": req.start_date.isoformat() if req.start_date else None,
            "end_date": req.end_date.isoformat() if req.end_date else None,
            "created_at": req.created_at.isoformat()
        })
    
    return result


@app.post("/api/supervisor/leave-request/{request_id}/approve")
def supervisor_approve_leave_request(
    request_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Supervisor approves or rejects leave request"""
    
    # Get supervisor by role
    supervisor = db.query(User).filter(User.role == "supervisor").first()
    
    if not supervisor:
        raise HTTPException(status_code=404, detail="Supervisor not found")
    
    leave_request = db.query(LeaveRequest).filter(LeaveRequest.id == request_id).first()
    if not leave_request:
        raise HTTPException(status_code=404, detail="Leave request not found")
    
    approved = data.get('approved', False)
    response_message = data.get('response', '')
    
    # Update status
    leave_request.status = "approved" if approved else "rejected"
    leave_request.response = response_message
    leave_request.responded_at = datetime.now()
    db.commit()
    
    # Send push notification to student
    background_tasks.add_task(
        send_push_notification,
        leave_request.attachee_id,
        "ðŸ“ Leave Request Update",
        f"Your leave request '{leave_request.title}' has been {leave_request.status}. {response_message}"
    )
    
    # Create notification for student
    notification = Notification(
        user_id=leave_request.attachee_id,
        title="Leave Request Update",
        message=f"Your leave request '{leave_request.title}' has been {leave_request.status}. {response_message}",
        type="leave_request"
    )
    db.add(notification)
    db.commit()
    
    return {
        "message": f"Leave request {leave_request.status} successfully",
        "request_id": request_id,
        "status": leave_request.status
    }

# ==================== ATTACHEE TASKS ====================

@app.get("/api/attachee/tasks/{user_id}")
def get_my_tasks(user_id: int, db: Session = Depends(get_db_local)):
    """Get all tasks assigned to an attachee"""
    tasks = db.query(Task).filter(
        Task.assigned_to_id == user_id
    ).order_by(Task.due_date.asc()).all()
    
    return [
        {
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "status": t.status,
            "feedback": t.feedback,
            "created_at": t.created_at.isoformat()
        }
        for t in tasks
    ]

@app.post("/api/attachee/tasks/{task_id}/complete")
def complete_task(task_id: int, db: Session = Depends(get_db_local)):
    """Mark a task as completed"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task.status = "completed"
    task.completed_at = datetime.now()
    db.commit()
    
    return {"message": "Task marked as completed"}

# ==================== ATTACHEE REPORTS ====================

@app.get("/api/attachee/reports/{user_id}")
def get_my_reports(user_id: int, db: Session = Depends(get_db_local)):
    """Get all reports submitted by an attachee"""
    reports = db.query(Report).filter(
        Report.attachee_id == user_id
    ).order_by(Report.submitted_at.desc()).all()
    
    return [
        {
            "id": r.id,
            "report_type": r.report_type,
            "title": r.title,
            "file_url": _public_upload_url(r.file_url),
            "submitted_at": r.submitted_at.isoformat(),
            "feedback": r.feedback
        }
        for r in reports
    ]

@app.post("/api/supervisor/logbook/{entry_id}/feedback")
def give_logbook_feedback(entry_id: int, feedback: str, db: Session = Depends(get_db_local)):
    """Provide feedback on a logbook entry"""
    entry = db.query(LogbookEntry).filter(LogbookEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    
    entry.feedback = feedback
    entry.feedback_given_at = datetime.now()
    db.commit()
    
    return {"message": "Feedback submitted"}

@app.post("/api/supervisor/task")
def create_supervisor_task(
    data: dict,
    db: Session = Depends(get_db_local)
):
    """Create a task, optionally assigning it to a student."""

    assigned_to_id = data.get("assigned_to_id")
    assigned_by_id = data.get("assigned_by_id")
    title = (data.get("title") or "").strip()
    description = data.get("description")
    due_date = data.get("due_date")
    priority = data.get("priority", "medium")

    if not assigned_by_id:
        raise HTTPException(status_code=400, detail="assigned_by_id is required")
    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    task = Task(
        assigned_to_id=assigned_to_id,
        assigned_by_id=assigned_by_id,
        title=title,
        description=description,
        due_date=date.fromisoformat(due_date) if due_date else None,
        priority=priority,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    if assigned_to_id:
        notification_url = "/tasks.html"
        send_push_notification(
            assigned_to_id,
            "New Task Assigned",
            f"You have a new task: {title}",
            notification_url
        )
        db.add(Notification(
            user_id=assigned_to_id,
            title="New Task Assigned",
            message=f"You have a new task: {title}",
            type="task",
            action_url=notification_url
        ))
        db.commit()

    return {
        "message": "Task created" if not assigned_to_id else "Task assigned",
        "task": _serialize_supervisor_task(task, db),
    }


def _serialize_supervisor_task(task: Task, db: Session) -> dict:
    student = None
    if task.assigned_to_id:
        student = db.query(User).filter(User.id == task.assigned_to_id).first()

    return {
        "id": task.id,
        "assigned_to_id": task.assigned_to_id,
        "assigned_by_id": task.assigned_by_id,
        "student_name": student.full_name if student else "",
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "priority": task.priority,
        "report_path": task.report_path,
        "report_filename": task.report_filename,
        "feedback": task.feedback,
        "rating": task.rating,
        "has_report": bool(task.report_path),
    }

@app.get("/api/supervisor/tasks/{supervisor_id}")
def get_assigned_tasks(supervisor_id: int, db: Session = Depends(get_db_local)):
    """Get tasks assigned by this supervisor"""

    tasks = db.query(Task).filter(
        Task.assigned_by_id == supervisor_id
    ).order_by(Task.created_at.desc()).all()

    return [_serialize_supervisor_task(task, db) for task in tasks]


@app.put("/api/supervisor/task/{task_id}")
def update_supervisor_task(
    task_id: int,
    data: dict,
    db: Session = Depends(get_db_local)
):
    """Update a supervisor task."""

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if "title" in data:
        title = (data.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="title cannot be empty")
        task.title = title

    if "description" in data:
        task.description = data.get("description")

    if "due_date" in data:
        due_date = data.get("due_date")
        task.due_date = date.fromisoformat(due_date) if due_date else None

    if "priority" in data:
        task.priority = data.get("priority", task.priority)

    if "assigned_to_id" in data:
        task.assigned_to_id = data.get("assigned_to_id")

    db.commit()
    db.refresh(task)

    return {
        "message": "Task updated successfully",
        "task": _serialize_supervisor_task(task, db),
    }

@app.post("/api/supervisor/leave-request/{request_id}/approve")
def approve_leave_request(request_id: int, approved: bool, response: str, db: Session = Depends(get_db_local)):
    """Approve or reject a leave request"""
    request_obj = db.query(LeaveRequest).filter(LeaveRequest.id == request_id).first()
    if not request_obj:
        raise HTTPException(status_code=404, detail="Request not found")
    
    request_obj.status = "approved" if approved else "rejected"
    request_obj.response = response
    request_obj.responded_at = datetime.now()
    db.commit()
    
    return {"message": f"Request {request_obj.status}"}

@app.post("/api/supervisor/leave-request/{request_id}/process")
def process_leave_request_by_supervisor(
    request_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Supervisor processes a leave request (approve or reject)"""
    
    leave_request = db.query(LeaveRequest).filter(LeaveRequest.id == request_id).first()
    if not leave_request:
        raise HTTPException(status_code=404, detail="Leave request not found")
    
    approved = data.get('approved', False)
    response_message = data.get('response', '')
    
    # Update the request
    leave_request.status = "approved" if approved else "rejected"
    leave_request.response = response_message
    leave_request.responded_at = datetime.now()
    db.commit()
    
    # Send push notification to student
    background_tasks.add_task(
        send_push_notification,
        leave_request.attachee_id,
        "ðŸ“ Leave Request Update",
        f"Your leave request '{leave_request.title}' has been {leave_request.status}. {response_message}"
    )
    
    # Create notification for student
    notification = Notification(
        user_id=leave_request.attachee_id,
        title="Leave Request Update",
        message=f"Your leave request '{leave_request.title}' has been {leave_request.status}. {response_message}",
        type="leave_request"
    )
    db.add(notification)
    db.commit()
    
    return {
        "message": f"Leave request {leave_request.status} successfully",
        "request_id": request_id,
        "status": leave_request.status
    }

@app.delete("/api/supervisor/task/{task_id}")
def delete_task(
    task_id: int,
    db: Session = Depends(get_db_local)
):
    """Delete a task (only if not completed)"""
    
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Optional: Only allow deletion of pending tasks
    if task.status == "completed":
        raise HTTPException(status_code=400, detail="Cannot delete completed tasks")
    
    db.delete(task)
    db.commit()
    
    return {"message": "Task deleted successfully"}

# ==================== COORDINATOR ENDPOINTS ====================

@app.get("/api/coordinator/applications")
def get_all_applications(db: Session = Depends(get_db_local)):
    """Get all attachment applications"""
    applications = db.query(Application).order_by(Application.submitted_at.desc()).all()
    
    result = []
    for app in applications:
        student = db.query(User).filter(User.id == app.attachee_id).first()
        result.append({
            "id": app.id,
            "student_name": student.full_name if student else "",
            "student_id": app.attachee_id,
            "department": app.department_applied,
            "status": app.status,
            "submitted_at": app.submitted_at.isoformat(),
            "feedback": app.feedback
        })
    
    return result

@app.post("/api/coordinator/application/{app_id}/review")
def review_application(
    app_id: int,
    approved: bool,
    feedback: str = None,
    assigned_department: str = None,
    assigned_supervisor_id: int = None,
    db: Session = Depends(get_db_local)
):
    """Review and process an application"""
    application = db.query(Application).filter(Application.id == app_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    
    application.status = "approved" if approved else "rejected"
    application.feedback = feedback
    application.reviewed_at = datetime.now()
    
    if approved:
        profile = db.query(AttacheeProfile).filter(
            AttacheeProfile.user_id == application.attachee_id
        ).first()
        if profile:
            profile.placement_status = "approved"
            if assigned_department:
                profile.department = assigned_department
            if assigned_supervisor_id:
                profile.assigned_supervisor_id = assigned_supervisor_id
    
    db.commit()
    
    return {"message": f"Application {application.status}"}

@app.get("/api/coordinator/students")
def get_all_students(db: Session = Depends(get_db_local)):
    """Get all attachees"""
    students = db.query(User).filter(User.role == "attachee").all()
    
    result = []
    for s in students:
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == s.id).first()
        result.append({
            "id": s.id,
            "username": s.username,
            "full_name": s.full_name,
            "email": s.email,
            "student_id": profile.student_id if profile else None,
            "course": profile.course if profile else None,
            "placement_status": profile.placement_status if profile else None
        })
    
    return result

@app.get("/api/coordinator/supervisors")
def get_all_supervisors(db: Session = Depends(get_db_local)):
    """Get school supervisors captured on contract forms.

    These are external institution supervisors, not system users with role=supervisor.
    """
    supervisors_by_key = {}

    def clean(value):
        return str(value or "").strip()

    def supervisor_key(name, phone="", email="", school=""):
        parts = [clean(name).lower(), clean(phone).lower(), clean(email).lower(), clean(school).lower()]
        return "|".join(parts)

    def add_supervisor(name, phone="", email="", school="", department="", faculty="", position="", student=None, source=""):
        name = clean(name)
        if not name:
            return

        phone = clean(phone)
        email = clean(email)
        school = clean(school)
        key = supervisor_key(name, phone, email, school)

        if key not in supervisors_by_key:
            supervisors_by_key[key] = {
                "id": f"school-{len(supervisors_by_key) + 1}",
                "full_name": name,
                "email": email,
                "phone": phone,
                "school": school,
                "department": clean(department),
                "faculty": clean(faculty),
                "position": clean(position),
                "source": source,
                "is_active": True,
                "student_ids": set(),
                "students": []
            }

        supervisor = supervisors_by_key[key]
        for field, value in {
            "email": email,
            "phone": phone,
            "school": school,
            "department": clean(department),
            "faculty": clean(faculty),
            "position": clean(position),
        }.items():
            if value and not supervisor.get(field):
                supervisor[field] = value

        if student:
            student_id = student.get("id")
            if student_id and student_id not in supervisor["student_ids"]:
                supervisor["student_ids"].add(student_id)
                supervisor["students"].append(student)

    contracts = db.query(Contract).filter(
        Contract.school_supervisor.isnot(None),
        Contract.school_supervisor != ""
    ).all()

    for contract in contracts:
        attachee = db.query(User).filter(User.id == contract.attachee_id).first()
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == contract.attachee_id).first()
        add_supervisor(
            name=contract.school_supervisor,
            phone=contract.school_supervisor_phone,
            school=contract.school or (profile.institution if profile else ""),
            department=profile.department if profile else "",
            student={
                "id": contract.attachee_id,
                "name": attachee.full_name if attachee else contract.full_name or "Unknown",
                "student_id": profile.student_id if profile else "",
                "contract_number": contract.contract_number,
            },
            source="contract"
        )

    result = []
    for supervisor in supervisors_by_key.values():
        supervisor["students_assigned"] = len(supervisor["student_ids"])
        supervisor.pop("student_ids", None)
        result.append(supervisor)

    return sorted(result, key=lambda item: item.get("full_name", "").lower())
    """Get all supervisors"""
    supervisors = db.query(User).filter(User.role == "supervisor").all()
    
    result = []
    for s in supervisors:
        profile = db.query(SupervisorProfile).filter(SupervisorProfile.user_id == s.id).first()
        result.append({
            "id": s.id,
            "full_name": s.full_name,
            "department": profile.department if profile else None,
            "position": profile.position if profile else None
        })
    
    return result



@app.get("/api/coordinator/departments")
def get_departments(db: Session = Depends(get_db_local)):
    """Get all departments"""
    departments = db.query(Department).all()
    return [{"id": d.id, "name": d.name, "description": d.description} for d in departments]

# ==================== COMMON ENDPOINTS ====================

@app.get("/api/notifications/{user_id}")
def get_notifications(user_id: int, db: Session = Depends(get_db_local)):
    """Get user notifications"""
    notifications = db.query(Notification).filter(
        Notification.user_id == user_id
    ).order_by(Notification.created_at.desc()).limit(50).all()
    
    return [
        {
            "id": n.id,
            "title": n.title,
            "message": n.message,
            "type": n.type,
            "is_read": n.is_read,
            "created_at": n.created_at.isoformat() if n.created_at else None,
            "action_url": n.action_url
        }
        for n in notifications
    ]

@app.post("/api/notifications/{notif_id}/read")
def mark_notification_read(notif_id: int, db: Session = Depends(get_db_local)):
    """Mark notification as read"""
    notification = db.query(Notification).filter(Notification.id == notif_id).first()
    if notification:
        notification.is_read = True
        db.commit()
    return {"message": "Marked as read"}

@app.post("/api/notifications/create")
def create_notification(
    user_id: int,
    title: str,
    message: str,
    type: str,
    action_url: str = None,
    db: Session = Depends(get_db_local)
):
    """Create a notification for a user"""
    notification = Notification(
        user_id=user_id,
        title=title,
        message=message,
        type=type,
        action_url=action_url
    )
    db.add(notification)
    db.commit()
    
    return {"message": "Notification created"}

# ==================== FILE UPLOADS ====================

@app.post("/api/upload/cv/{user_id}")
async def upload_cv(user_id: int, file: UploadFile = File(...), db: Session = Depends(get_db_local)):
    """Upload CV file"""
    if not file.filename.endswith(('.pdf', '.doc', '.docx')):
        raise HTTPException(status_code=400, detail="Only PDF and Word documents are allowed")
    
    file_path = Config.UPLOAD_DIR / f"cv_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == user_id).first()
    if profile:
        profile.cv_url = str(file_path)
        db.commit()
    
    return {"message": "CV uploaded", "file_path": str(file_path)}

@app.post("/api/upload/report/{user_id}")
async def upload_report(
    user_id: int, 
    report_type: str, 
    title: str, 
    file: UploadFile = File(...), 
    db: Session = Depends(get_db_local)
):
    """Upload report file"""
    file_path = Config.UPLOAD_DIR / f"report_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    report = Report(
        attachee_id=user_id,
        report_type=report_type,
        title=title,
        file_url=str(file_path)
    )
    db.add(report)
    db.commit()
    
    return {"message": "Report uploaded", "report_id": report.id}

# ==================== APPLICATION FORM ENDPOINTS ====================

@app.post("/api/application-form/start/{attachee_id}")
def start_application_form(attachee_id: int, db: Session = Depends(get_db_local)):
    """Start a new application form session"""
    existing = db.query(ApplicationForm).filter(
        ApplicationForm.attachee_id == attachee_id,
        ApplicationForm.status == "in_progress"
    ).first()
    
    if existing:
        return {
            "form_id": existing.id,
            "session_start": existing.session_start.isoformat(),
            "session_expiry": existing.session_expiry.isoformat(),
            "message": "Existing session found"
        }
    
    session_start = datetime.now()
    session_expiry = session_start + timedelta(minutes=10)
    
    form = ApplicationForm(
        attachee_id=attachee_id,
        session_start=session_start,
        session_expiry=session_expiry,
        status="in_progress"
    )
    db.add(form)
    db.commit()
    db.refresh(form)
    
    return {
        "form_id": form.id,
        "session_start": form.session_start.isoformat(),
        "session_expiry": form.session_expiry.isoformat(),
        "message": "Form session started. You have 10 minutes to complete."
    }

# ==================== OVERTIME REQUEST ENDPOINTS ====================

@app.post("/api/application-form/request-overtime/{form_id}")
def request_overtime(
    form_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Student requests overtime for application form - ALLOWED EVEN IF EXPIRED"""
    
    form = db.query(ApplicationForm).filter(ApplicationForm.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")
    
    # Check if form is already completed
    if form.status == "completed":
        raise HTTPException(status_code=400, detail="Form already submitted")
    
    # REMOVE the session expiry check - allow overtime request even if expired
    # Don't check if datetime.now() > form.session_expiry
    
    minutes = data.get('minutes', 10)
    
    # Check if overtime already requested
    if form.overtime_requested:
        raise HTTPException(status_code=400, detail="Overtime already requested")
    
    # Update form with overtime request
    form.overtime_requested = True
    form.overtime_minutes = minutes
    # Extend session expiry immediately so student can continue
    form.session_expiry = datetime.now() + timedelta(minutes=minutes)
    db.commit()
    
    # Get student name for notification
    student = db.query(User).filter(User.id == form.attachee_id).first()
    student_name = student.full_name if student else f"Student {form.attachee_id}"
    
    # Notify all coordinators
    coordinators = db.query(User).filter(User.role == "coordinator").all()
    for coord in coordinators:
        background_tasks.add_task(
            send_push_notification,
            coord.id,
            "â° Overtime Request",
            f"{student_name} has requested {minutes} minutes overtime for application form"
        )
        
        notification = Notification(
            user_id=coord.id,
            title="Overtime Request",
            message=f"Student {student_name} (ID: {form.attachee_id}) requests {minutes} minutes extension",
            type="overtime_request"
        )
        db.add(notification)
    
    db.commit()
    
    return {
        "message": "Overtime request submitted",
        "form_id": form_id,
        "minutes": minutes,
        "new_expiry": form.session_expiry.isoformat(),
        "status": "pending"
    }

@app.post("/api/application-form/approve-overtime/{form_id}")
def approve_overtime(
    form_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Coordinator approves or rejects overtime request"""
    
    form = db.query(ApplicationForm).filter(ApplicationForm.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")
    
    approved = data.get('approved', False)
    
    if approved:
        # Add extra minutes to session expiry
        extra_minutes = form.overtime_minutes or 10
        form.session_expiry = datetime.now() + timedelta(minutes=extra_minutes)
        form.overtime_approved = True
        message = f"Overtime approved! Extended by {extra_minutes} minutes."
        
        # Send push notification to student
        background_tasks.add_task(
            send_push_notification,
            form.attachee_id,
            "âœ… Overtime Approved",
            f"Your overtime request has been approved! You have +{extra_minutes} minutes to complete the form. New expiry: {form.session_expiry.strftime('%H:%M:%S')}"
        )
    else:
        form.overtime_approved = False
        message = "Overtime request denied."
        
        # Send push notification to student
        background_tasks.add_task(
            send_push_notification,
            form.attachee_id,
            "âŒ Overtime Denied",
            "Your overtime request has been denied. Please submit the form before time expires."
        )
    
    db.commit()
    
    # Get student name for notification
    student = db.query(User).filter(User.id == form.attachee_id).first()
    student_name = student.full_name if student else f"Student {form.attachee_id}"
    
    # Notify coordinator that request was processed
    coordinators = db.query(User).filter(User.role == "coordinator").all()
    for coord in coordinators:
        notification = Notification(
            user_id=coord.id,
            title="Overtime Request Processed",
            message=f"Overtime request for {student_name} has been {'approved' if approved else 'denied'}.",
            type="overtime"
        )
        db.add(notification)
    db.commit()
    
    return {
        "message": message,
        "form_id": form_id,
        "overtime_approved": approved,
        "new_expiry": form.session_expiry.isoformat() if approved else None
    }


@app.get("/api/application-form/check/{form_id}")
def check_form_status(form_id: int, db: Session = Depends(get_db_local)):
    """Check form status and overtime approval"""
    
    form = db.query(ApplicationForm).filter(ApplicationForm.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")
    
    return {
        "form_id": form.id,
        "status": form.status,
        "session_expiry": form.session_expiry.isoformat() if form.session_expiry else None,
        "overtime_requested": form.overtime_requested,
        "overtime_approved": form.overtime_approved,
        "overtime_denied": form.overtime_requested and not form.overtime_approved,
        "overtime_minutes": form.overtime_minutes
    }


@app.get("/api/coordinator/overtime-requests")
def get_overtime_requests(db: Session = Depends(get_db_local)):
    """Get pending overtime requests for coordinator"""
    
    # Get forms that have overtime requested but not yet approved or denied
    forms = db.query(ApplicationForm).filter(
        ApplicationForm.overtime_requested == True,
        ApplicationForm.overtime_approved == False,
        ApplicationForm.status == "in_progress"
    ).order_by(ApplicationForm.session_expiry.asc()).all()
    
    result = []
    for form in forms:
        student = db.query(User).filter(User.id == form.attachee_id).first()
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == form.attachee_id).first()
        
        result.append({
            "id": form.id,
            "form_id": form.id,
            "student_name": student.full_name if student else "Unknown",
            "student_id": profile.student_id if profile else "N/A",
            "requested_minutes": form.overtime_minutes or 10,
            "requested_at": form.session_start.isoformat() if form.session_start else None,
            "session_expiry": form.session_expiry.isoformat() if form.session_expiry else None,
            "form_title": "Application Form",
            "status": "pending"
        })

    return result


@app.post("/api/application-form/submit/{form_id}")
async def submit_application_form(
    form_id: int,
    request: FastAPIRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Submit completed application form with all details"""
    
    try:
        form_data = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")
    
    form = db.query(ApplicationForm).filter(ApplicationForm.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")
    
    if datetime.now() > form.session_expiry and not form.overtime_approved:
        form.status = "expired"
        db.commit()
        raise HTTPException(status_code=400, detail="Session expired. Please request overtime or restart.")
    
    attachee = db.query(User).filter(User.id == form.attachee_id).first()
    if not attachee:
        raise HTTPException(status_code=404, detail="Attachee not found")
    
    # Check if email is already used by another user (excluding current user)
    new_email = form_data.get('email')
    if new_email:
        existing_user = db.query(User).filter(
            User.email == new_email,
            User.id != form.attachee_id
        ).first()
        if existing_user:
            raise HTTPException(
                status_code=400, 
                detail=f"Email '{new_email}' is already registered to another user. Please use a different email address."
            )
    
    # Update User table
    if form_data.get('full_name'):
        attachee.full_name = form_data.get('full_name')
    if new_email:
        attachee.email = new_email
    if form_data.get('mobile'):
        attachee.phone = form_data.get('mobile')
    
    # Update or create AttacheeProfile
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == form.attachee_id).first()
    if not profile:
        profile = AttacheeProfile(user_id=form.attachee_id)
        db.add(profile)
    
    if not profile.student_id:
        profile.student_id = f"MFB{form.attachee_id:06d}"
    
    # Update profile with form data
    if form_data.get('date_of_birth'):
        try:
            profile.date_of_birth = datetime.fromisoformat(form_data.get('date_of_birth')).date()
        except:
            pass
    if form_data.get('gender'):
        profile.gender = form_data.get('gender')
    if form_data.get('physical_address'):
        profile.address = form_data.get('physical_address')
    if form_data.get('postal_address'):
        profile.postal_address = form_data.get('postal_address')
    if form_data.get('county'):
        profile.county = form_data.get('county')
    if form_data.get('institution'):
        profile.institution = form_data.get('institution')
    if form_data.get('course'):
        profile.course = form_data.get('course')
    if form_data.get('education_level'):
        profile.education_level = form_data.get('education_level')
    if form_data.get('year_of_study'):
        try:
            year_str = form_data.get('year_of_study')
            if year_str and year_str[0].isdigit():
                profile.year_of_study = int(year_str[0])
        except:
            profile.year_of_study = 1
    if form_data.get('academic_year'):
        profile.academic_year = form_data.get('academic_year')
    if form_data.get('department_applied'):
        profile.department_applied = form_data.get('department_applied')
    
    # Store form data as JSON
    form.personal_details = json.dumps({
        'full_name': form_data.get('full_name'),
        'date_of_birth': form_data.get('date_of_birth'),
        'id_number': form_data.get('id_number'),
        'gender': form_data.get('gender'),
        'physical_address': form_data.get('physical_address'),
        'postal_address': form_data.get('postal_address'),
        'mobile': form_data.get('mobile'),
        'email': form_data.get('email'),
        'county': form_data.get('county')
    })
    
    form.education_background = json.dumps({
        'institution': form_data.get('institution'),
        'course': form_data.get('course'),
        'education_level': form_data.get('education_level'),
        'year_of_study': form_data.get('year_of_study'),
        'academic_year': form_data.get('academic_year')
    })
    
    form.skills = json.dumps({
        'technical_skills': form_data.get('technical_skills'),
        'computer_skills': form_data.get('computer_skills'),
        'languages': form_data.get('languages'),
        'extracurricular': form_data.get('extracurricular')
    })
    
    form.experience = json.dumps({
        'previous_experience': form_data.get('experience'),
        'motivation': form_data.get('motivation')
    })
    
    form.attachment_details = json.dumps({
        'start_date': form_data.get('start_date'),
        'duration': form_data.get('duration')
    })
    
    form.reference_details = json.dumps({
        'referee_name': form_data.get('referee_name'),
        'referee_org': form_data.get('referee_org'),
        'referee_position': form_data.get('referee_position'),
        'referee_contact': form_data.get('referee_contact')
    })
    
    form.signature = form_data.get('signature')
    form.declaration_accepted = form_data.get('declaration_accepted', False)
    
    form.status = "completed"
    form.submitted_at = datetime.now()
    profile.placement_status = "applied"
    
    db.commit()
    
    # Notify coordinators
    coordinators = db.query(User).filter(User.role == "coordinator").all()
    for coord in coordinators:
        notification = Notification(
            user_id=coord.id,
            title="New Application Form Submitted",
            message=f"Attachee {attachee.full_name or attachee.username} has completed the application form",
            type="application_form"
        )
        db.add(notification)
    db.commit()
    
    # Send push notification to student
    background_tasks.add_task(send_push_notification, attachee.id, "âœ… Application Submitted", "Your application has been submitted successfully!")
    
    # Check and notify status change
    background_tasks.add_task(check_and_notify_status_change, attachee.id, db)
    
    return {
        "message": "Application form submitted successfully",
        "form_id": form.id
    }

@app.get("/api/auth/check-email")
def check_email(email: str, db: Session = Depends(get_db_local)):
    """Check if email is already registered"""
    user = db.query(User).filter(User.email == email).first()
    return {
        "exists": user is not None,
        "user_id": user.id if user else None
    }

# ==================== ATTACHEE STATUS ENDPOINTS ====================

@app.get("/api/attachee/application-status/{user_id}")
def get_attachee_application_status(user_id: int, db: Session = Depends(get_db_local)):
    """Get attachee application form status"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    app_form = db.query(ApplicationForm).filter(
        ApplicationForm.attachee_id == user_id,
        ApplicationForm.status == "completed"
    ).first()
    has_application_form = app_form is not None
    
    return {
        "has_application_form": has_application_form,
        "submitted_at": app_form.submitted_at.isoformat() if app_form else None
    }

@app.get("/api/attachee/status/{user_id}")
def get_attachee_status(user_id: int, db: Session = Depends(get_db_local)):
    """Get attachee's current onboarding status"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == user_id).first()
    
    has_application_form = db.query(ApplicationForm).filter(
        ApplicationForm.attachee_id == user_id,
        ApplicationForm.status == "completed"
    ).first() is not None

    application_review = db.query(Application).filter(
        Application.attachee_id == user_id
    ).order_by(Application.reviewed_at.desc(), Application.submitted_at.desc()).first()

    latest_contract_form = db.query(Contract).filter(
        Contract.attachee_id == user_id,
        Contract.status.in_(["sent", "rejected"])
    ).order_by(Contract.updated_at.desc(), Contract.created_at.desc()).first()
    has_pending_contract_form = latest_contract_form is not None and latest_contract_form.status == "sent"
    has_contract_changes_requested = latest_contract_form is not None and latest_contract_form.status == "rejected"

    filled_contract = db.query(Contract).filter(
        Contract.attachee_id == user_id,
        Contract.status == "filled"
    ).order_by(Contract.filled_at.desc(), Contract.created_at.desc()).first()

    pending_interview = db.query(Interview).filter(
        Interview.attachee_id == user_id,
        Interview.status == "scheduled"
    ).order_by(Interview.scheduled_time.desc()).first()

    completed_interview = db.query(Interview).filter(
        Interview.attachee_id == user_id,
        Interview.status == "completed"
    ).order_by(Interview.interview_time_end.desc(), Interview.scheduled_time.desc()).first()

    pending_contract_approval = db.query(Contract).filter(
        Contract.attachee_id == user_id,
        Contract.status == "pending_supervisor"
    ).order_by(Contract.coordinator_approved_at.desc(), Contract.updated_at.desc()).first()

    signed_contract = db.query(Contract).filter(
        Contract.attachee_id == user_id,
        Contract.status == "approved"
    ).order_by(Contract.supervisor_approved_at.desc(), Contract.updated_at.desc()).first()
    is_profile_placed = bool(profile and profile.placement_status == "placed")

    latest_contract_activity = None
    if filled_contract:
        latest_contract_activity = filled_contract.filled_at or filled_contract.signed_at or filled_contract.created_at

    followup_pending_interview = None
    if pending_interview and latest_contract_activity:
        if pending_interview.scheduled_time and pending_interview.scheduled_time >= latest_contract_activity:
            followup_pending_interview = pending_interview

    followup_completed_interview = None
    if completed_interview and latest_contract_activity:
        completed_time = completed_interview.interview_time_end or completed_interview.scheduled_time
        if completed_time and completed_time >= latest_contract_activity:
            followup_completed_interview = completed_interview

    is_application_approved = bool(application_review and application_review.status == "approved")

    if signed_contract or is_profile_placed:
        current_step = "placed"
    elif pending_contract_approval:
        current_step = "contract_pending"
    elif followup_pending_interview:
        current_step = "followup_interview_scheduled"
    elif followup_completed_interview:
        current_step = "followup_interview_completed"
    elif filled_contract:
        current_step = "contract_filled"
    elif pending_interview:
        current_step = "interview_scheduled"
    elif completed_interview:
        current_step = "interview_completed"
    elif has_contract_changes_requested:
        current_step = "contract_changes_requested"
    elif has_pending_contract_form:
        current_step = "contract_form_pending"
    elif is_application_approved:
        current_step = "application_approved"
    elif has_application_form:
        current_step = "form_completed"
    else:
        current_step = "registration_complete"

    return {
        "current_step": current_step,
        "has_application_form": has_application_form,
        "application_status": application_review.status if application_review else None,
        "application_approved": is_application_approved,
        "has_pending_contract_form": has_pending_contract_form,
        "has_contract_changes_requested": has_contract_changes_requested,
        "has_filled_contract": filled_contract is not None,
        "has_pending_interview": pending_interview is not None,
        "has_completed_interview": completed_interview is not None,
        "has_followup_pending_interview": followup_pending_interview is not None,
        "has_followup_completed_interview": followup_completed_interview is not None,
        "has_pending_contract": pending_contract_approval is not None,
        "has_signed_contract": signed_contract is not None,
        "is_placed": signed_contract is not None or is_profile_placed,
        "scheduled_interview_time": pending_interview.scheduled_time.isoformat() if pending_interview else None
    }

@app.get("/api/attachee/pending-interview/{user_id}")
def get_pending_interview(user_id: int, db: Session = Depends(get_db_local)):
    """Get pending interview for attachee"""
    interview = db.query(Interview).filter(
        Interview.attachee_id == user_id,
        Interview.status == "scheduled"
    ).first()
    
    if interview:
        return {
            "has_pending_interview": True,
            "scheduled_time": interview.scheduled_time.isoformat(),
            "duration": interview.duration_minutes
        }
    return {"has_pending_interview": False}

@app.get("/api/attachee/application-form/{user_id}")
def get_attachee_application_form(user_id: int, db: Session = Depends(get_db_local)):
    """Get attachee's submitted application form data"""
    
    # Check if user exists
    user = db.query(User).filter(User.id == user_id, User.role == "attachee").first()
    if not user:
        raise HTTPException(status_code=404, detail="Attachee not found")
    
    # Get the most recent completed application form
    application_form = db.query(ApplicationForm).filter(
        ApplicationForm.attachee_id == user_id,
        ApplicationForm.status == "completed"
    ).order_by(ApplicationForm.submitted_at.desc()).first()
    
    if not application_form:
        return {
            "has_form": False,
            "message": "No application form submitted yet"
        }
    
    # Parse JSON fields
    personal_details = {}
    education_background = {}
    skills = {}
    experience = {}
    attachment_details = {}
    reference_details = {}
    
    if application_form.personal_details:
        try:
            personal_details = json.loads(application_form.personal_details)
        except:
            pass
    
    if application_form.education_background:
        try:
            education_background = json.loads(application_form.education_background)
        except:
            pass
    
    if application_form.skills:
        try:
            skills = json.loads(application_form.skills)
        except:
            pass
    
    if application_form.experience:
        try:
            experience = json.loads(application_form.experience)
        except:
            pass
    
    if application_form.attachment_details:
        try:
            attachment_details = json.loads(application_form.attachment_details)
        except:
            pass
    
    if application_form.reference_details:
        try:
            reference_details = json.loads(application_form.reference_details)
        except:
            pass
    
    # Get profile data for additional info
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == user_id).first()
    
    return {
        "has_form": True,
        "form_id": application_form.id,
        "submitted_at": application_form.submitted_at.isoformat() if application_form.submitted_at else None,
        "status": application_form.status,
        "personal_details": {
            "full_name": personal_details.get('full_name', user.full_name or ''),
            "date_of_birth": personal_details.get('date_of_birth', ''),
            "id_number": personal_details.get('id_number', ''),
            "gender": personal_details.get('gender', ''),
            "physical_address": personal_details.get('physical_address', ''),
            "postal_address": personal_details.get('postal_address', ''),
            "mobile": personal_details.get('mobile', user.phone or ''),
            "email": personal_details.get('email', user.email or ''),
            "county": personal_details.get('county', ''),
            "nationality": personal_details.get('nationality', 'Kenyan')
        },
        "education_background": {
            "institution": education_background.get('institution', profile.institution if profile else ''),
            "course": education_background.get('course', profile.course if profile else ''),
            "education_level": education_background.get('education_level', ''),
            "year_of_study": education_background.get('year_of_study', profile.year_of_study if profile else ''),
            "academic_year": education_background.get('academic_year', ''),
            "admission_number": education_background.get('admission_number', ''),
            "expected_completion": education_background.get('expected_completion', '')
        },
        "skills": {
            "technical_skills": skills.get('technical_skills', ''),
            "computer_skills": skills.get('computer_skills', ''),
            "languages": skills.get('languages', ''),
            "extracurricular": skills.get('extracurricular', ''),
            "certifications": skills.get('certifications', '')
        },
        "experience": {
            "previous_experience": experience.get('previous_experience', ''),
            "motivation": experience.get('motivation', ''),
            "career_goals": experience.get('career_goals', ''),
            "availability": experience.get('availability', '')
        },
        "attachment_details": {
            "preferred_department": attachment_details.get('preferred_department', ''),
            "start_date": attachment_details.get('start_date', ''),
            "duration": attachment_details.get('duration', '12 weeks'),
            "special_requirements": attachment_details.get('special_requirements', '')
        },
        "reference_details": {
            "referee_name": reference_details.get('referee_name', ''),
            "referee_org": reference_details.get('referee_org', ''),
            "referee_position": reference_details.get('referee_position', ''),
            "referee_contact": reference_details.get('referee_contact', ''),
            "referee_email": reference_details.get('referee_email', '')
        },
        "declaration_accepted": application_form.declaration_accepted or False,
        "signature": application_form.signature
    }

# ==================== INTERVIEW ENDPOINTS ====================

@app.get("/api/interviews/pending/{coordinator_id}")
def get_pending_interviews(coordinator_id: int, db: Session = Depends(get_db_local)):
    """Get pending interviews for coordinator"""
    interviews = db.query(Interview).filter(
        Interview.coordinator_id == coordinator_id,
        Interview.status == "scheduled"
    ).order_by(Interview.scheduled_time.asc()).all()
    
    result = []
    for i in interviews:
        attachee = db.query(User).filter(User.id == i.attachee_id).first()
        result.append({
            "id": i.id,
            "attachee_name": attachee.full_name if attachee else "Unknown",
            "scheduled_time": i.scheduled_time.isoformat(),
            "duration": i.duration_minutes
        })
    
    return result

@app.post("/api/interviews/start/{interview_id}")
def start_interview(interview_id: int, db: Session = Depends(get_db_local)):
    """Start an interview (timer begins)"""
    interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    interview.status = "in_progress"
    interview.interview_time_start = datetime.now()
    interview.interview_time_end = datetime.now() + timedelta(minutes=interview.duration_minutes)
    db.commit()
    
    return {
        "message": "Interview started",
        "end_time": interview.interview_time_end.isoformat(),
        "duration_minutes": interview.duration_minutes
    }

@app.get("/api/interviews/check-timer/{interview_id}")
def check_interview_timer(interview_id: int, db: Session = Depends(get_db_local)):
    """Check remaining time for interview"""
    interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    if interview.status != "in_progress":
        return {"status": interview.status}
    
    remaining = (interview.interview_time_end - datetime.now()).total_seconds()
    
    return {
        "status": "in_progress",
        "remaining_seconds": max(0, remaining),
        "end_time": interview.interview_time_end.isoformat()
    }

@app.post("/api/interviews/complete/{interview_id}")
def complete_interview(
    interview_id: int, 
    background_tasks: BackgroundTasks,
    notes: str = None, 
    db: Session = Depends(get_db_local)
):
    """Complete an interview"""
    interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    interview.status = "completed"
    interview.interview_time_end = datetime.now()
    if notes:
        interview.notes = notes
    db.commit()
    
    notification = Notification(
        user_id=interview.coordinator_id,
        title="Interview Completed",
        message=f"Interview with Attachee ID {interview.attachee_id} completed. Next please.",
        type="interview"
    )
    db.add(notification)
    db.commit()
    
    # Send push notification to student
    background_tasks.add_task(send_push_notification, interview.attachee_id, "âœ… Interview Completed", "Your interview has been completed. Next step: Contract preparation.")
    
    # Check and notify status change
    background_tasks.add_task(check_and_notify_status_change, interview.attachee_id, db)
    
    return {"message": "Interview completed"}

@app.get("/api/interviews/completed/{coordinator_id}")
def get_completed_interviews(coordinator_id: int, db: Session = Depends(get_db_local)):
    """Get completed interviews for coordinator"""
    interviews = db.query(Interview).filter(
        Interview.coordinator_id == coordinator_id,
        Interview.status == "completed"
    ).order_by(Interview.scheduled_time.desc()).all()
    
    result = []
    for i in interviews:
        attachee = db.query(User).filter(User.id == i.attachee_id).first()
        result.append({
            "id": i.id,
            "attachee_id": i.attachee_id,
            "attachee_name": attachee.full_name if attachee else "Unknown",
            "scheduled_time": i.scheduled_time.isoformat(),
            "completed_at": i.interview_time_end.isoformat() if i.interview_time_end else None,
            "duration_minutes": i.duration_minutes,
            "status": i.status,
            "notes": i.notes
        })
    
    return result

@app.get("/api/interviews/supervisor/pending/{supervisor_id}")
def get_supervisor_pending_interviews(supervisor_id: int, db: Session = Depends(get_db_local)):
    """Get pending interviews for supervisor - interviews that need to be conducted"""
    
    # First, verify this is a supervisor
    supervisor = db.query(User).filter(User.id == supervisor_id, User.role == "supervisor").first()
    if not supervisor:
        raise HTTPException(status_code=403, detail="Only supervisors can access this endpoint")
    
    # Get scheduled interviews that haven't been started yet
    # Also include in_progress interviews that might have been started but not completed
    interviews = db.query(Interview).filter(
        Interview.status.in_(["scheduled", "in_progress"])
    ).order_by(Interview.scheduled_time.asc()).all()
    
    result = []
    for interview in interviews:
        attachee = db.query(User).filter(User.id == interview.attachee_id).first()
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == interview.attachee_id).first()
        
        scheduled_time = interview.scheduled_time
        if isinstance(scheduled_time, datetime):
            scheduled_time_str = scheduled_time.strftime("%Y-%m-%d %H:%M:%S")
        else:
            scheduled_time_str = str(scheduled_time)
        
        result.append({
            "id": interview.id,
            "attachee_id": interview.attachee_id,
            "attachee_name": attachee.full_name if attachee else "Unknown",
            "student_id": profile.student_id if profile else "N/A",
            "scheduled_time": scheduled_time_str,
            "duration_minutes": interview.duration_minutes,
            "status": interview.status,
            "notes": interview.notes
        })
    
    return result
# ==================== CONTRACT ENDPOINTS ====================

@app.post("/api/contracts/create/{attachee_id}")
def create_contract(
    attachee_id: int,
    amount_paid: float,
    payment_reference: str = None,
    db: Session = Depends(get_db_local)
):
    """Create contract for attachee (initiated by coordinator)"""
    contract_number = f"CTR-{datetime.now().strftime('%Y%m%d')}-{attachee_id}"
    
    contract = Contract(
        attachee_id=attachee_id,
        contract_number=contract_number,
        amount_paid=amount_paid,
        payment_reference=payment_reference,
        status="pending_coordinator"
    )
    db.add(contract)
    db.commit()
    db.refresh(contract)
    
    return {"message": "Contract created", "contract_id": contract.id, "contract_number": contract_number}

@app.post("/api/contracts/sign/{contract_id}")
def sign_contract(
    contract_id: int, 
    signed_by: str, 
    terms_agreed: bool,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Attachee signs the contract"""
    if not terms_agreed:
        raise HTTPException(status_code=400, detail="You must agree to the terms and conditions")
    
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    
    contract.terms_agreed = True
    contract.signed_by = signed_by
    contract.signed_at = datetime.now()
    contract.status = "pending_supervisor"
    db.commit()
    
    attachee = db.query(User).filter(User.id == contract.attachee_id).first()
    coordinators = db.query(User).filter(User.role == "coordinator").all()
    for coord in coordinators:
        notification = Notification(
            user_id=coord.id,
            title="Contract Signed",
            message=f"Attachee {attachee.full_name if attachee else 'Unknown'} has signed the contract",
            type="contract"
        )
        db.add(notification)
    db.commit()
    
    # Send push notification
    background_tasks.add_task(send_push_notification, contract.attachee_id, "ðŸ“ Contract Signed", "Your contract has been signed and sent for approval.")
    
    return {"message": "Contract signed successfully", "status": "pending_supervisor"}

@app.post("/api/contracts/coordinator-approve/{contract_id}")
def coordinator_approve_contract(
    contract_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Coordinator approves contract and forwards to supervisor"""
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    
    contract.coordinator_approved = True
    contract.coordinator_approved_at = datetime.now()
    contract.status = "pending_supervisor"
    db.commit()
    
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == contract.attachee_id).first()
    if profile and profile.assigned_supervisor_id:
        contract.supervisor_id = profile.assigned_supervisor_id
        
        notification = Notification(
            user_id=profile.assigned_supervisor_id,
            title="Contract Pending Approval",
            message=f"Contract {contract.contract_number} requires your approval for placement",
            type="contract"
        )
        db.add(notification)
    else:
        supervisors = db.query(User).filter(User.role == "supervisor").all()
        for sup in supervisors:
            notification = Notification(
                user_id=sup.id,
                title="Contract Pending Approval",
                message=f"Contract {contract.contract_number} requires supervisor approval",
                type="contract"
            )
            db.add(notification)
    
    db.commit()
    
    # Send push notification to student
    background_tasks.add_task(send_push_notification, contract.attachee_id, "âœ… Contract Approved by Coordinator", "Your contract has been approved by the coordinator and sent to supervisor.")
    
    return {"message": "Contract forwarded to supervisor for approval"}


@app.get("/api/contracts/all")
def get_all_contracts(db: Session = Depends(get_db_local)):
    """Get all contracts for coordinator view"""
    contracts = db.query(Contract).order_by(Contract.created_at.desc()).all()
    
    result = []
    for c in contracts:
        attachee = db.query(User).filter(User.id == c.attachee_id).first()
        result.append({
            "id": c.id,
            "attachee_id": c.attachee_id,
            "student_name": attachee.full_name if attachee else "Unknown",
            "contract_number": c.contract_number,
            "amount_paid": c.amount_paid,
            "status": c.status,
            "signed_at": c.signed_at.isoformat() if c.signed_at else None,
            "coordinator_approved": c.coordinator_approved,
            "supervisor_approved": c.supervisor_approved
        })
    
    return result

# ==================== STUDENT DETAILS & ACTIONS ====================

@app.get("/api/students/{student_id}/details")
def get_student_details(student_id: int, db: Session = Depends(get_db_local)):
    """Get complete student details for coordinator/supervisor"""
    user = db.query(User).filter(User.id == student_id, User.role == "attachee").first()
    if not user:
        raise HTTPException(status_code=404, detail="Student not found")
    
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == student_id).first()
    application_form = db.query(ApplicationForm).filter(
        ApplicationForm.attachee_id == student_id,
        ApplicationForm.status == "completed"
    ).first()
    interview = db.query(Interview).filter(Interview.attachee_id == student_id).order_by(Interview.created_at.desc()).first()
    contract = db.query(Contract).filter(Contract.attachee_id == student_id).order_by(Contract.created_at.desc()).first()
    
    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "email": user.email,
            "phone": user.phone,
            "created_at": user.created_at.isoformat()
        },
        "profile": {
            "student_id": profile.student_id if profile else None,
            "course": profile.course if profile else None,
            "institution": profile.institution if profile else None,
            "year_of_study": profile.year_of_study if profile else None,
            "department": profile.department if profile else None,
            "placement_status": profile.placement_status if profile else None,
            "start_date": profile.start_date.isoformat() if profile and profile.start_date else None,
            "end_date": profile.end_date.isoformat() if profile and profile.end_date else None
        },
        "application_form": {
            "submitted_at": application_form.submitted_at.isoformat() if application_form else None,
            "has_details": bool(application_form)
        } if application_form else None,
        "interview": {
            "scheduled_time": interview.scheduled_time.isoformat() if interview else None,
            "status": interview.status if interview else None,
            "notes": interview.notes if interview else None
        } if interview else None,
        "contract": {
            "contract_number": contract.contract_number if contract else None,
            "amount_paid": contract.amount_paid if contract else None,
            "status": contract.status if contract else None,
            "signed_at": contract.signed_at.isoformat() if contract and contract.signed_at else None,
            "approved_at": contract.supervisor_approved_at.isoformat() if contract and contract.supervisor_approved_at else None
        } if contract else None
    }

@app.post("/api/students/{student_id}/action")
def take_student_action(
    student_id: int,
    action: str,
    background_tasks: BackgroundTasks,
    reason: str = None,
    db: Session = Depends(get_db_local)
):
    """Take disciplinary action on a student (suspend, dismiss, expel)"""
    user = db.query(User).filter(User.id == student_id, User.role == "attachee").first()
    if not user:
        raise HTTPException(status_code=404, detail="Student not found")
    
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == student_id).first()
    
    action_messages = {
        'suspend': {
            'status': 'suspended',
            'user_active': False,
            'message': f"Attachee {user.full_name} has been suspended."
        },
        'dismiss': {
            'status': 'dismissed',
            'user_active': False,
            'message': f"Attachee {user.full_name} has been dismissed from the attachment program."
        },
        'expel': {
            'status': 'expelled',
            'user_active': False,
            'message': f"Attachee {user.full_name} has been expelled."
        }
    }
    
    if action not in action_messages:
        raise HTTPException(status_code=400, detail="Invalid action")
    
    action_info = action_messages[action]
    
    user.is_active = action_info['user_active']
    if profile:
        profile.placement_status = action_info['status']
    
    notification = Notification(
        user_id=student_id,
        title=f"Attachment {action.title()}ed",
        message=action_info['message'] + (f" Reason: {reason}" if reason else ""),
        type="disciplinary"
    )
    db.add(notification)
    
    coordinators = db.query(User).filter(User.role == "coordinator").all()
    for coord in coordinators:
        notif = Notification(
            user_id=coord.id,
            title=f"Student {action.title()}ed",
            message=f"{user.full_name} ({profile.student_id if profile else 'N/A'}) has been {action}ed.",
            type="disciplinary"
        )
        db.add(notif)
    
    db.commit()
    
    # Send push notification
    background_tasks.add_task(send_push_notification, student_id, f"âš ï¸ Account {action.title()}ed", action_info['message'])
    
    return {
        "message": action_info['message'],
        "status": action_info['status']
    }

# Add these imports at the top
from fastapi import WebSocket, WebSocketDisconnect
import asyncio

# ==================== WEBSOCKET MANAGER ====================

class ConnectionManager:
    """Manage WebSocket connections for real-time updates"""
    def __init__(self):
        self.active_connections: dict = {}
        self.user_status_cache = {}
    
    async def connect(self, websocket: WebSocket, user_id: int):
        try:
            await websocket.accept()
            self.active_connections[user_id] = websocket
            print(f"âœ… WebSocket connected for user {user_id}")
        except Exception as e:
            print(f"Error accepting WebSocket for user {user_id}: {e}")
    
    def disconnect(self, user_id: int):
        if user_id in self.active_connections:
            try:
                websocket = self.active_connections.pop(user_id)
                # Don't await close - just create task and forget
                asyncio.create_task(self._safe_close(websocket))
            except Exception as e:
                print(f"Error disconnecting user {user_id}: {e}")
            finally:
                print(f"âŒ WebSocket disconnected for user {user_id}")

    async def _safe_close(self, websocket):
        """Safely close websocket without errors"""
        try:
            if hasattr(websocket, 'client_state'):
                # Only close if not already closed
                from starlette.websockets import WebSocketState
                if websocket.client_state != WebSocketState.DISCONNECTED:
                    await websocket.close()
            else:
                await websocket.close()
        except Exception:
            pass  # Ignore close errors
    
    async def send_personal_message(self, message: dict, user_id: int):
        if user_id in self.active_connections:
            try:
                websocket = self.active_connections[user_id]
                await websocket.send_json(message)
                return True
            except Exception as e:
                print(f"Error sending message to user {user_id}: {e}")
                self.disconnect(user_id)
        return False
    
    async def broadcast_to_role(self, message: dict, role: str, db: Session):
        users = db.query(User).filter(User.role == role).all()
        for user in users:
            await self.send_personal_message(message, user.id)
    
    async def notify_status_change(self, user_id: int, old_status: str, new_status: str):
        message = {
            "type": "status_change",
            "old_status": old_status,
            "new_status": new_status,
            "message": self.get_status_message(new_status),
            "timestamp": datetime.now().isoformat()
        }
        await self.send_personal_message(message, user_id)
    
    def get_status_message(self, status: str) -> str:
        messages = {
            'interview_scheduled': 'ðŸ“… Your interview has been scheduled! Check your dashboard.',
            'interview_completed': 'âœ… Interview completed! Next step: Contract preparation.',
            'contract_pending': 'ðŸ“ Your contract is ready for signing!',
            'placed': 'ðŸŽ‰ Congratulations! Your placement has been confirmed! Welcome to Mfano Bora!',
            'form_completed': 'âœ… Application submitted successfully! Under review.',
            'application_review': 'ðŸ“‹ Your application is being reviewed.'
        }
        messages = {
            'form_completed': 'Application submitted successfully. It is now with the coordinator for review.',
            'application_approved': 'Your application has been approved. The next step is interview scheduling.',
            'interview_scheduled': 'Your interview has been scheduled. Check your dashboard for the details.',
            'interview_completed': 'Your interview is complete. The next step is contract preparation.',
            'contract_form_pending': 'Your contract form is ready. Please fill and submit it.',
            'contract_filled': 'Your contract has been submitted and is awaiting review.',
            'followup_interview_scheduled': 'A follow-up interview has been scheduled before contract approval.',
            'followup_interview_completed': 'The follow-up interview is complete. Your contract can now move to approval.',
            'contract_pending': 'Your contract is under approval.',
            'placed': 'Congratulations! Your placement has been confirmed. Welcome to Mfano Bora!',
            'application_review': 'Your application is being reviewed.'
        }
        return messages.get(status, 'Your application status has been updated.')

# Create global connection manager
manager = ConnectionManager()

# ==================== WEBSOCKET ENDPOINT ====================

# In main.py, update the websocket_endpoint function
@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    """WebSocket endpoint for real-time updates"""
    try:
        await manager.connect(websocket, user_id)
        
        # Send initial connection confirmation
        await manager.send_personal_message({
            "type": "connection",
            "message": "Connected to real-time update server",
            "timestamp": datetime.now().isoformat()
        }, user_id)
        
        # Keep connection alive with ping/pong
        while True:
            try:
                # Set a timeout for receiving messages
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                
                # Handle ping/pong for keep-alive
                if data == "ping":
                    await websocket.send_text("pong")
                else:
                    print(f"Received from user {user_id}: {data}")
                    
            except asyncio.TimeoutError:
                # Send a ping to check if connection is still alive
                try:
                    await websocket.send_text("ping")
                except:
                    break
            except WebSocketDisconnect:
                print(f"WebSocket disconnected for user {user_id}")
                break
            except Exception as e:
                print(f"WebSocket error for user {user_id}: {e}")
                break
                
    except Exception as e:
        print(f"WebSocket connection error for user {user_id}: {e}")
    finally:
        manager.disconnect(user_id)

# ==================== MODIFIED STATUS CHECK WITH WEBSOCKET ====================

def check_and_notify_status_change_ws(user_id: int, db: Session):
    """Check status change and notify via WebSocket"""
    from main import get_attachee_status
    
    # Get current status
    current_status_data = get_attachee_status(user_id, db)
    current_step = current_status_data.get('current_step', 'registration_complete')
    
    # Get previously stored status
    previous_status = manager.user_status_cache.get(user_id)
    
    if previous_status and previous_status != current_step:
        # Status changed - send WebSocket notification
        print(f"ðŸ“¢ Status changed for user {user_id}: {previous_status} -> {current_step}")
        
        # Send WebSocket message
        asyncio.create_task(manager.notify_status_change(user_id, previous_status, current_step))
    
    # Store new status
    manager.user_status_cache[user_id] = current_step
    
    return current_step

# ==================== UPDATE EXISTING ENDPOINTS TO USE WEBSOCKET ====================

# Modify the schedule_interview endpoint
@app.post("/api/interviews/schedule")
async def schedule_interview(
    request: FastAPIRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Schedule an interview for an attachee"""
    try:
        # Parse JSON body
        data = await request.json()
        
        attachee_id = data.get('attachee_id')
        scheduled_time = data.get('scheduled_time')
        scheduler_id = data.get('scheduler_id') or data.get('coordinator_id') or data.get('supervisor_id')
        notes = data.get('notes', '')
        
        # Validate required fields
        if not attachee_id:
            raise HTTPException(status_code=400, detail="attachee_id is required")
        if not scheduled_time:
            raise HTTPException(status_code=400, detail="scheduled_time is required")
        if not scheduler_id:
            raise HTTPException(status_code=400, detail="scheduler_id is required")
        
        scheduled_datetime = datetime.fromisoformat(scheduled_time.replace('Z', '+00:00'))
        scheduler = db.query(User).filter(User.id == scheduler_id).first()
        if not scheduler or scheduler.role not in ["coordinator", "supervisor"]:
            raise HTTPException(status_code=403, detail="Only coordinators or supervisors can schedule interviews")
        
        # Check if interview already exists
        existing = db.query(Interview).filter(
            Interview.attachee_id == attachee_id,
            Interview.status == "scheduled"
        ).first()
        
        if existing:
            return {
                "message": "Interview already scheduled",
                "interview_id": existing.id,
                "existing": True
            }
        
        interview = Interview(
            attachee_id=attachee_id,
            coordinator_id=scheduler_id,
            scheduled_time=scheduled_datetime,
            duration_minutes=6,
            status="scheduled",
            notes=notes
        )
        db.add(interview)
        db.commit()
        db.refresh(interview)
        
        notification = Notification(
            user_id=attachee_id,
            title="Interview Scheduled",
            message=f"Your interview is scheduled for {scheduled_datetime.strftime('%Y-%m-%d %H:%M')}",
            type="interview"
        )
        db.add(notification)
        db.commit()
        
        # Send push notification
        background_tasks.add_task(
            send_push_notification, 
            attachee_id, 
            "ðŸ“… Interview Scheduled", 
            f"Your interview is scheduled for {scheduled_datetime.strftime('%B %d, %Y at %I:%M %p')}"
        )
        
        # Check and notify status change
        background_tasks.add_task(check_and_notify_status_change, attachee_id, db)
        
        # Send WebSocket notification if available
        try:
            await manager.send_personal_message({
                "type": "interview_scheduled",
                "title": "ðŸ“… Interview Scheduled",
                "message": f"Your interview is scheduled for {scheduled_datetime.strftime('%B %d, %Y at %I:%M %p')}",
                "scheduled_time": scheduled_datetime.isoformat(),
                "timestamp": datetime.now().isoformat()
            }, attachee_id)
        except:
            pass
        
        return {"message": "Interview scheduled", "interview_id": interview.id}
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    except Exception as e:
        print(f"Error scheduling interview: {e}")
        raise HTTPException(status_code=400, detail=f"Error scheduling interview: {str(e)}")

# Modify the complete_interview endpoint
@app.post("/api/interviews/complete/{interview_id}")
async def complete_interview(
    interview_id: int, 
    background_tasks: BackgroundTasks,
    notes: str = None, 
    db: Session = Depends(get_db_local)
):
    """Complete an interview"""
    interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    interview.status = "completed"
    interview.interview_time_end = datetime.now()
    if notes:
        interview.notes = notes
    db.commit()
    
    notification = Notification(
        user_id=interview.coordinator_id,
        title="Interview Completed",
        message=f"Interview with Attachee ID {interview.attachee_id} completed. Next please.",
        type="interview"
    )
    db.add(notification)
    db.commit()
    
    # Send WebSocket notification
    await manager.send_personal_message({
        "type": "interview_completed",
        "title": "âœ… Interview Completed",
        "message": "Your interview has been completed. Next step: Contract preparation.",
        "timestamp": datetime.now().isoformat()
    }, interview.attachee_id)
    
    # Check and notify status change
    background_tasks.add_task(check_and_notify_status_change_ws, interview.attachee_id, db)
    
    return {"message": "Interview completed"}

@app.get("/api/interviews/{interview_id}")
def get_interview_details(
    interview_id: int,
    db: Session = Depends(get_db_local)
):
    """Get interview details by ID"""
    interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    # Get attachee details
    attachee = db.query(User).filter(User.id == interview.attachee_id).first()
    
    return {
        "id": interview.id,
        "attachee_id": interview.attachee_id,
        "attachee_name": attachee.full_name if attachee else "Unknown",
        "scheduled_time": interview.scheduled_time.isoformat(),
        "duration_minutes": interview.duration_minutes,
        "status": interview.status,
        "notes": interview.notes,
        "completed_at": interview.interview_time_end.isoformat() if interview.interview_time_end else None
    }

# Modify the contract approval endpoint
# ==================== CONTRACT APPROVAL ENDPOINTS (CLEANED - NO DUPLICATES) ====================

@app.post("/api/contracts/supervisor-approve/{contract_id}")
def supervisor_approve_contract(
    contract_id: int,
    supervisor_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Supervisor approves contract and confirms placement"""
    
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    
    # Update contract
    contract.supervisor_approved = True
    contract.supervisor_approved_at = datetime.now()
    contract.supervisor_id = supervisor_id
    contract.status = "approved"
    db.commit()
    
    # Update attachee profile
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == contract.attachee_id).first()
    if profile:
        profile.placement_status = "placed"
        if not profile.assigned_supervisor_id:
            profile.assigned_supervisor_id = supervisor_id
        db.commit()
    
    # ========== NEW: Update user's contract approval date ==========
    user = db.query(User).filter(User.id == contract.attachee_id).first()
    if user:
        user.contract_approved_at = contract.supervisor_approved_at
        user.payment_deadline_days = 30  # Set policy days (30 days to pay)
        db.commit()
        print(f"âœ… Contract approval date recorded for user {user.id}: {user.contract_approved_at}")
    # ========== END NEW ==========
    
    # Notify attachee
    background_tasks.add_task(
        send_push_notification,
        contract.attachee_id,
        "ðŸŽ‰ Placement Confirmed!",
        f"Congratulations! Your attachment has been approved. Welcome to Mfano Bora Africa Ltd!"
    )
    
    notification = Notification(
        user_id=contract.attachee_id,
        title="Placement Confirmed!",
        message=f"Your attachment has been approved. Welcome to Mfano Bora Africa Ltd!",
        type="placement"
    )
    db.add(notification)
    
    # Notify coordinator
    coordinators = db.query(User).filter(User.role == "coordinator").all()
    for coord in coordinators:
        background_tasks.add_task(
            send_push_notification,
            coord.id,
            "âœ… Placement Confirmed",
            f"Attachee {contract.full_name} has been placed successfully"
        )
    
    db.commit()
    
    return {"message": "Contract approved. Attachee placement confirmed!"}
    
# ==================== FACE RECOGNITION ENDPOINTS USING OPENCV ONLY ====================
import cv2
import base64
import numpy as np
from PIL import Image
from io import BytesIO
import json

@app.post("/api/face/register")
async def register_face(request: FastAPIRequest, db: Session = Depends(get_db_local)):
    """Register face with quality checks"""
    try:
        data = await request.json()
        user_id = data.get('user_id')
        photos = data.get('photos', [])
        
        if not user_id or not photos:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Missing required data"}
            )
        
        if len(photos) < 3:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Need at least 3 photos for registration"}
            )
        
        face_images = []
        quality_scores = []
        
        for idx, photo_data in enumerate(photos[:3]):
            # Decode base64 image
            if 'base64,' in photo_data:
                photo_data = photo_data.split('base64,')[1]
            
            image_bytes = base64.b64decode(photo_data)
            image = Image.open(BytesIO(image_bytes))
            
            # Convert PIL to OpenCV format
            img_cv = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
            
            # Detect face
            face_cascade = get_face_cascade()
            if face_cascade is None:
                return JSONResponse(status_code=500, content={"success": False, "message": "Face detection not initialized"})
            gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.3, 5)
            
            if len(faces) == 0:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": f"No face detected in photo {idx+1}. Please ensure your face is clearly visible."}
                )
            
            if len(faces) > 1:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": f"Multiple faces detected in photo {idx+1}. Please ensure only your face is visible."}
                )
            
            # Extract face ROI
            x, y, w, h = faces[0]
            face_roi = gray[y:y+h, x:x+w]
            
            # Check image quality (blur detection) - more lenient for registration
            laplacian_var = cv2.Laplacian(face_roi, cv2.CV_64F).var()
            if laplacian_var < 40:  # Lower threshold for registration
                print(f"âš ï¸ Photo {idx+1} quality score: {laplacian_var:.2f} (slightly blurry but accepted)")
            else:
                print(f"âœ… Photo {idx+1} quality score: {laplacian_var:.2f}")
            
            # Resize and store
            face_resized = cv2.resize(face_roi, (100, 100))
            _, buffer = cv2.imencode('.jpg', face_resized)
            face_images.append(base64.b64encode(buffer).decode('utf-8'))
            quality_scores.append(laplacian_var)
            
            print(f"âœ… Photo {idx+1}: Face detected and stored")
        
        # Store face images
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == user_id).first()
        if not profile:
            return JSONResponse(
                status_code=404,
                content={"success": False, "message": "User profile not found"}
            )
        
        profile.face_encoding = json.dumps(face_images)
        profile.face_registered_at = datetime.now()
        profile.face_verification_count = 0
        db.commit()
        
        return JSONResponse(
            content={
                "success": True,
                "message": f"Face registered successfully using {len(face_images)} photos"
            }
        )
        
    except Exception as e:
        print(f"Face registration error: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"Registration error: {str(e)}"}
        )


@app.post("/api/attendance/face-verify")
async def verify_face(request: FastAPIRequest, db: Session = Depends(get_db_local)):
    """Verify face using enhanced histogram comparison"""
    try:
        data = await request.json()
        user_id = data.get('user_id')
        image_data = data.get('image')
        action = data.get('action', 'checkin')
        
        print(f"ðŸ” Face verification request - User: {user_id}, Action: {action}")
        
        if not user_id or not image_data:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Missing required data"}
            )
        
        # Get stored face images
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == user_id).first()
        if not profile or not profile.face_encoding:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Face not registered. Please try checking in again for registration."}
            )
        
        stored_faces = json.loads(profile.face_encoding)
        print(f"ðŸ“¸ Found {len(stored_faces)} stored face images")
        
        # Process the image data
        if 'base64,' in image_data:
            image_data = image_data.split('base64,')[1]
        elif ',' in image_data:
            image_data = image_data.split(',')[1]
        
        try:
            image_bytes = base64.b64decode(image_data)
        except Exception as e:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Invalid image data format"}
            )
        
        # Convert bytes to OpenCV image
        nparr = np.frombuffer(image_bytes, np.uint8)
        img_cv = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img_cv is None:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Could not read image data"}
            )
        
        # Detect face using OpenCV Haar Cascade
        face_cascade = get_face_cascade()
        if face_cascade is None:
            return JSONResponse(status_code=500, content={"success": False, "message": "Face detection not initialized"})
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)
        
        print(f"ðŸ‘¤ Detected {len(faces)} face(s)")
        
        if len(faces) == 0:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "No face detected. Please ensure your face is clearly visible."}
            )
        
        if len(faces) > 1:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Multiple faces detected. Please ensure only your face is visible."}
            )
        
        # Extract and process current face
        x, y, w, h = faces[0]
        current_face = gray[y:y+h, x:x+w]
        current_face_resized = cv2.resize(current_face, (100, 100))
        
        # Check image quality (blur detection)
        laplacian_var = cv2.Laplacian(current_face_resized, cv2.CV_64F).var()
        print(f"ðŸ“¸ Image quality score: {laplacian_var:.2f}")
        
        if laplacian_var < 30:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Image too blurry. Please ensure good lighting and steady camera."}
            )
        
        # Compare with stored faces
        best_match_score = 0
        match_scores = []
        
        for idx, stored_face_b64 in enumerate(stored_faces):
            try:
                stored_face_bytes = base64.b64decode(stored_face_b64)
                stored_face_array = cv2.imdecode(np.frombuffer(stored_face_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
                
                if stored_face_array is None:
                    continue
                
                # Calculate histogram correlation
                hist_current = cv2.calcHist([current_face_resized], [0], None, [256], [0, 256])
                hist_stored = cv2.calcHist([stored_face_array], [0], None, [256], [0, 256])
                score = cv2.compareHist(hist_current, hist_stored, cv2.HISTCMP_CORREL)
                
                match_scores.append(score)
                print(f"ðŸ“Š Face {idx+1} match score: {score:.4f}")
                
                if score > best_match_score:
                    best_match_score = score
            except Exception as e:
                print(f"âš ï¸ Error comparing stored face {idx+1}: {e}")
                continue
        
        if not match_scores:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Could not compare faces. Please try again."}
            )
        
        # Calculate average match score
        avg_match_score = sum(match_scores) / len(match_scores)
        print(f"ðŸ“Š Best match: {best_match_score:.4f}, Average: {avg_match_score:.4f}")
        
        # BALANCED THRESHOLDS - Secure but not too strict
        MIN_MATCH_SCORE = 0.55  # 55% minimum match (balanced)
        MIN_AVG_SCORE = 0.45     # 45% average match
        
        # Check if best match meets minimum threshold
        if best_match_score >= MIN_MATCH_SCORE and avg_match_score >= MIN_AVG_SCORE:
            # Success - face verified
            profile.face_last_verified_at = datetime.now()
            profile.face_verification_count = (profile.face_verification_count or 0) + 1
            
            # Store verification history
            verification_history = []
            if hasattr(profile, 'face_verification_history') and profile.face_verification_history:
                try:
                    verification_history = json.loads(profile.face_verification_history)
                except:
                    verification_history = []
            
            verification_history.append({
                "timestamp": datetime.now().isoformat(),
                "action": action,
                "match_score": best_match_score,
                "avg_score": avg_match_score
            })
            # Keep last 50 verifications
            verification_history = verification_history[-50:]
            profile.face_verification_history = json.dumps(verification_history)
            
            db.commit()
            
            confidence_percent = round(best_match_score * 100, 1)
            print(f"âœ… Face verified! Confidence: {confidence_percent}%")
            
            return JSONResponse(
                content={
                    "success": True,
                    "message": f"âœ… Face verified successfully! ({confidence_percent}% match)",
                    "confidence": best_match_score
                }
            )
        else:
            confidence_percent = round(best_match_score * 100, 1)
            required_percent = round(MIN_MATCH_SCORE * 100, 1)
            print(f"âŒ Face verification failed. Best match: {confidence_percent}% (need {required_percent}%)")
            
            return JSONResponse(
                status_code=400,
                content={
                    "success": False, 
                    "message": f"Face does not match registered user. ({confidence_percent}% match, need {required_percent}% minimum). Please ensure good lighting and try again."
                }
            )
        
    except Exception as e:
        print(f"âŒ Face verification error: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"Verification error: {str(e)}"}
        )

@app.get("/api/face/check/{user_id}")
async def check_face_registered(user_id: int, db: Session = Depends(get_db_local)):
    """Check if user has registered face"""
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == user_id).first()
    
    return {
        "has_face": bool(profile and profile.face_encoding),
        "registered_at": profile.face_registered_at.isoformat() if profile and profile.face_registered_at else None,
        "verification_count": profile.face_verification_count if profile else 0
    }


@app.delete("/api/face/delete/{user_id}")
async def delete_face_registration(user_id: int, db: Session = Depends(get_db_local)):
    """Delete user's face registration (for re-registration)"""
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == user_id).first()
    
    if profile:
        profile.face_encoding = None
        profile.face_registered_at = None
        profile.face_verification_count = 0
        db.commit()
        return {"success": True, "message": "Face registration deleted"}
    
    return {"success": False, "message": "User not found"}

# Add these endpoints to main.py for coordinator application forms

@app.get("/api/coordinator/application-forms")
def get_application_forms(db: Session = Depends(get_db_local)):
    """Get all submitted application forms for coordinator review"""
    
    # Get all completed application forms with user details
    forms = db.query(ApplicationForm).filter(
        ApplicationForm.status == "completed"
    ).order_by(ApplicationForm.submitted_at.desc()).all()
    
    result = []
    for form in forms:
        user = db.query(User).filter(User.id == form.attachee_id).first()
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == form.attachee_id).first()
        application_review = db.query(Application).filter(
            Application.attachee_id == form.attachee_id
        ).order_by(Application.submitted_at.desc()).first()
        
        # Parse personal details
        personal_details = {}
        if form.personal_details:
            try:
                personal_details = json.loads(form.personal_details)
            except:
                pass
        
        # Determine actual application status based on student's placement and interview
        actual_status = "pending"
        
        # Check if student is already placed
        if profile and profile.placement_status == "placed":
            actual_status = "placed"
        elif application_review and application_review.status == "rejected":
            actual_status = "rejected"
        elif application_review and application_review.status == "approved":
            actual_status = "accepted"
        elif profile and profile.placement_status == "approved":
            actual_status = "accepted"
        # Check if student has completed interview
        elif profile and profile.placement_status == "interview_completed":
            actual_status = "interview_completed"
        # Check if interview is scheduled
        else:
            interview = db.query(Interview).filter(
                Interview.attachee_id == form.attachee_id,
                Interview.status == "scheduled"
            ).first()
            if interview:
                actual_status = "interview_scheduled"
        
        result.append({
            "id": form.id,
            "form_id": form.id,
            "attachee_user_id": form.attachee_id,
            "student_name": user.full_name if user else "Unknown",
            "student_id": profile.student_id if profile else "N/A",
            "email": user.email if user else "",
            "phone": user.phone if user else "",
            "institution": profile.institution if profile else "",
            "course": profile.course if profile else "",
            "year_of_study": profile.year_of_study if profile else "",
            "department": personal_details.get('department_applied', profile.department_applied or "Not specified"),
            "status": actual_status,  # Use actual status, not hardcoded "pending"
            "submitted_at": form.submitted_at.isoformat() if form.submitted_at else "",
            "feedback": application_review.feedback if application_review else "",
            "interview_status": actual_status,  # Add interview status for dashboard filtering
            "placement_status": profile.placement_status if profile else "not_applied"
        })
    
    return result


@app.get("/api/supervisor/application-forms/{supervisor_id}")
def get_supervisor_application_forms(supervisor_id: int, db: Session = Depends(get_db_local)):
    """Supervisor application review has been retired; coordinator handles it alone."""
    supervisor = db.query(User).filter(User.id == supervisor_id, User.role == "supervisor").first()
    if not supervisor:
        raise HTTPException(status_code=403, detail="Only supervisors can access this endpoint")
    return []


def process_application_form_review(
    form_id: int,
    data: dict,
    db: Session,
    background_tasks: BackgroundTasks | None = None
):
    """Persist coordinator review outcome for an application form."""
    form = db.query(ApplicationForm).filter(ApplicationForm.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Application form not found")

    approved = data.get('approved', False)
    feedback = data.get('feedback', '')
    reviewed_by = data.get('reviewed_by')

    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == form.attachee_id).first()

    personal_details = {}
    attachment_details = {}
    if form.personal_details:
        try:
            personal_details = json.loads(form.personal_details)
        except Exception:
            personal_details = {}
    if form.attachment_details:
        try:
            attachment_details = json.loads(form.attachment_details)
        except Exception:
            attachment_details = {}

    preferred_department = (
        attachment_details.get('preferred_department')
        or personal_details.get('department_applied')
        or (profile.department_applied if profile else None)
        or (profile.department if profile else None)
    )

    application = db.query(Application).filter(Application.attachee_id == form.attachee_id).first()
    if not application:
        application = Application(
            attachee_id=form.attachee_id,
            department_applied=preferred_department or "Not specified",
            submitted_at=form.submitted_at or datetime.now()
        )
        db.add(application)

    application.department_applied = preferred_department or application.department_applied or "Not specified"
    application.status = "approved" if approved else "rejected"
    application.feedback = feedback
    application.reviewed_at = datetime.now()
    if reviewed_by:
        application.reviewed_by = reviewed_by

    if profile and profile.placement_status != "placed":
        profile.placement_status = "approved" if approved else "not_applied"

    if approved:
        message = feedback if feedback else "Your application has been approved. You can now proceed to interview scheduling."
        title = "Application Approved"
    else:
        message = feedback if feedback else "Your application has been reviewed and was not approved."
        title = "Application Update"

    if background_tasks:
        background_tasks.add_task(
            send_push_notification,
            form.attachee_id,
            title,
            message
        )

    notification = Notification(
        user_id=form.attachee_id,
        title=title,
        message=message,
        type="application_review"
    )
    db.add(notification)
    db.commit()

    return {
        "message": "Application approved and ready for interview scheduling"
        if approved else
        "Application rejected successfully",
        "approved": approved,
        "application_status": application.status,
        "placement_status": profile.placement_status if profile else None
    }

@app.post("/api/coordinator/application-form/{form_id}/review")
def review_application_form(
    form_id: int,
    data: dict,
    db: Session = Depends(get_db_local)
):
    """Review an application form (approve/reject)"""
    return process_application_form_review(form_id, data, db)

# Add to main.py - Coordinator attendance endpoints

@app.get("/api/coordinator/attendance/{date}")
def get_attendance_for_date(date: str, db: Session = Depends(get_db_local)):
    """Get attendance for all students on a specific date"""
    target_date = datetime.fromisoformat(date).date()
    
    # Get all attachees
    students = db.query(User).filter(User.role == "attachee", User.is_active == True).all()
    
    result = []
    for student in students:
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == student.id).first()
        
        # Get attendance record for this date
        attendance = db.query(Attendance).filter(
            Attendance.attachee_id == student.id,
            Attendance.date == target_date
        ).first()
        
        if attendance:
            status = "present" if attendance.status == "present" else "absent"
            if attendance.check_in_time and attendance.check_in_time > datetime.now().replace(hour=9, minute=0).time():
                status = "late"
            
            result.append({
                "id": student.id,
                "student_id": profile.student_id if profile else "N/A",
                "full_name": student.full_name or student.username,
                "course": profile.course if profile else "N/A",
                "check_in_time": attendance.check_in_time.strftime("%H:%M:%S") if attendance.check_in_time else None,
                "check_out_time": attendance.check_out_time.strftime("%H:%M:%S") if attendance.check_out_time else None,
                "status": status
            })
        else:
            result.append({
                "id": student.id,
                "student_id": profile.student_id if profile else "N/A",
                "full_name": student.full_name or student.username,
                "course": profile.course if profile else "N/A",
                "check_in_time": None,
                "check_out_time": None,
                "status": "not_reported"
            })
    
    return result

@app.get("/api/coordinator/student-attendance/{student_id}")
def get_student_attendance_history(student_id: int, db: Session = Depends(get_db_local)):
    """Get attendance history for a specific student"""
    records = db.query(Attendance).filter(
        Attendance.attachee_id == student_id
    ).order_by(Attendance.date.desc()).all()
    
    return [
        {
            "date": r.date.isoformat(),
            "check_in_time": r.check_in_time.strftime("%H:%M:%S") if r.check_in_time else None,
            "check_out_time": r.check_out_time.strftime("%H:%M:%S") if r.check_out_time else None,
            "status": r.status
        }
        for r in records
    ]

@app.get("/api/coordinator/attendance-range")
def get_attendance_for_range(start_date: str, end_date: str, db: Session = Depends(get_db_local)):
    """Get attendance records for a date range"""
    start = datetime.fromisoformat(start_date).date()
    end = datetime.fromisoformat(end_date).date()
    
    # Get all attachees
    students = db.query(User).filter(User.role == "attachee", User.is_active == True).all()
    
    daily_records = []
    total_present = 0
    total_absent = 0
    total_late = 0
    
    current_date = start
    while current_date <= end:
        for student in students:
            profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == student.id).first()
            attendance = db.query(Attendance).filter(
                Attendance.attachee_id == student.id,
                Attendance.date == current_date
            ).first()
            
            status = "absent"
            if attendance:
                status = "present" if attendance.status == "present" else "absent"
                if attendance.check_in_time and attendance.check_in_time > datetime.now().replace(hour=9, minute=0).time():
                    status = "late"
            
            if status == "present":
                total_present += 1
            elif status == "late":
                total_late += 1
            elif status == "absent":
                total_absent += 1
            
            daily_records.append({
                "date": current_date.isoformat(),
                "student_name": student.full_name or student.username,
                "student_id": profile.student_id if profile else "N/A",
                "course": profile.course if profile else "N/A",
                "check_in": attendance.check_in_time.strftime("%H:%M:%S") if attendance and attendance.check_in_time else None,
                "check_out": attendance.check_out_time.strftime("%H:%M:%S") if attendance and attendance.check_out_time else None,
                "status": status.upper()
            })
        
        current_date += timedelta(days=1)
    
    return {
        "students": [{"id": s.id, "name": s.full_name} for s in students],
        "daily_records": daily_records,
        "summary": {
            "total_present": total_present,
            "total_absent": total_absent,
            "total_late": total_late,
            "total_students": len(students),
            "total_days": (end - start).days + 1
        }
    }

    # Add to main.py

@app.put("/api/users/update-profile/{user_id}")
def update_user_profile(user_id: int, data: dict, db: Session = Depends(get_db_local)):
    """Update user profile"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Update basic info
    if 'full_name' in data:
        user.full_name = data['full_name']
    if 'email' in data and data['email']:
        user.email = data['email']
    if 'phone' in data:
        user.phone = data['phone']
    
    # Update role-specific profile
    if user.role == 'coordinator':
        profile = db.query(CoordinatorProfile).filter(CoordinatorProfile.user_id == user_id).first()
        if profile:
            if 'department' in data:
                profile.department = data['department']
            if 'position' in data:
                profile.position = data['position']
            if 'office_location' in data:
                profile.office_location = data['office_location']
    elif user.role == 'supervisor':
        profile = db.query(SupervisorProfile).filter(SupervisorProfile.user_id == user_id).first()
        if profile:
            if 'employee_id' in data:
                profile.employee_id = data['employee_id']
            if 'department' in data:
                profile.department = data['department']
            if 'position' in data:
                profile.position = data['position']
    
    db.commit()
    
    return {"message": "Profile updated successfully"}

# Add this to main.py

@app.post("/api/users/change-password")
def change_password(
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Change user password"""
    user_id = data.get('user_id')
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    
    if not user_id or not current_password or not new_password:
        raise HTTPException(status_code=400, detail="Missing required fields")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Verify current password
    if not user.verify_password(current_password):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    
    # Validate new password strength
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    
    # Set new password
    user.set_password(new_password)
    user.password_set = True  # Mark that password has been set/changed
    user.updated_at = datetime.now()
    db.commit()
    
    # Send notification
    background_tasks.add_task(
        send_push_notification,
        user_id,
        "ðŸ” Password Changed",
        "Your password has been changed successfully. If this wasn't you, please contact the coordinator immediately."
    )
    
    notification = Notification(
        user_id=user_id,
        title="Password Changed",
        message="Your password has been changed successfully.",
        type="password_change"
    )
    db.add(notification)
    db.commit()
    
    return {"message": "Password changed successfully"}

@app.post("/api/users/logout-all/{user_id}")
def logout_all_devices(user_id: int, db: Session = Depends(get_db_local)):
    """Logout from all other devices"""
    # This is a placeholder - implement session management
    return {"message": "Logged out from all other devices"}

@app.post("/api/users/preferences/{user_id}")
def save_preferences(user_id: int, data: dict, db: Session = Depends(get_db_local)):
    """Save user preferences"""
    # This is a placeholder - implement preferences storage
    return {"message": "Preferences saved"}

# ==================== TRAINING MANAGEMENT ENDPOINTS ====================

@app.post("/api/trainings")
def create_training(
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local),
    # current_user: User = Depends(get_current_user)  # Add auth later
):
    """Create a new training session"""
    try:
        # Create training
        training = Training(
            title=data.get('title'),
            description=data.get('description'),
            start_datetime=datetime.fromisoformat(data.get('start_datetime')),
            venue=data.get('venue'),
            virtual_link=data.get('virtual_link'),
            created_by=1  # Replace with current_user.id
        )
        db.add(training)
        db.flush()
        
        # Add participants
        participant_ids = data.get('participant_ids', [])
        for attachee_id in participant_ids:
            participant = TrainingParticipant(
                training_id=training.id,
                attachee_id=attachee_id
            )
            db.add(participant)
        
        db.commit()
        
        # Send notifications to participants
        for attachee_id in participant_ids:
            background_tasks.add_task(
                send_push_notification,
                attachee_id,
                "ðŸ“š New Training Scheduled",
                f"New training: {data.get('title')} on {training.start_datetime.strftime('%B %d, %Y at %H:%M')}"
            )
        
        return {"message": "Training created successfully", "training_id": training.id}
        
    except Exception as e:
        db.rollback()
        print(f"Error creating training: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/trainings")
def get_trainings(db: Session = Depends(get_db_local)):
    """Get all trainings"""
    trainings = db.query(Training).order_by(Training.start_datetime.desc()).all()
    
    result = []
    for training in trainings:
        # Get participant count
        participant_count = db.query(TrainingParticipant).filter(
            TrainingParticipant.training_id == training.id
        ).count()
        
        # Check if attendance has been marked
        attendance_marked = db.query(TrainingAttendance).filter(
            TrainingAttendance.training_id == training.id
        ).first() is not None
        
        result.append({
            "id": training.id,
            "title": training.title,
            "description": training.description,
            "datetime": training.start_datetime.isoformat(),
            "venue": training.venue,
            "virtual_link": training.virtual_link,
            "participants_count": participant_count,
            "attendance_status": "marked" if attendance_marked else "pending"
        })
    
    return result


@app.get("/api/trainings/{training_id}")
def get_training(training_id: int, db: Session = Depends(get_db_local)):
    """Get training details"""
    training = db.query(Training).filter(Training.id == training_id).first()
    if not training:
        raise HTTPException(status_code=404, detail="Training not found")
    
    # Get participants
    participants = db.query(TrainingParticipant).filter(
        TrainingParticipant.training_id == training_id
    ).all()
    
    participant_list = []
    for p in participants:
        user = db.query(User).filter(User.id == p.attachee_id).first()
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == p.attachee_id).first()
        participant_list.append({
            "id": user.id,
            "name": user.full_name or user.username,
            "student_id": profile.student_id if profile else "N/A"
        })
    
    return {
        "id": training.id,
        "title": training.title,
        "description": training.description,
        "datetime": training.start_datetime.isoformat(),
        "venue": training.venue,
        "virtual_link": training.virtual_link,
        "participants": participant_list
    }


def _is_virtual_meeting(training: Training) -> bool:
    text = " ".join([
        training.title or "",
        training.description or "",
        training.venue or "",
        training.virtual_link or ""
    ]).lower()
    meeting_keywords = [
        "meeting",
        "sync",
        "stand-up",
        "standup",
        "1-on-1",
        "1 on 1",
        "mentorship",
        "zoom",
        "teams"
    ]
    return any(keyword in text for keyword in meeting_keywords)


def _training_attendance_status(status: str, notes: str = "") -> str:
    normalized = (status or "").lower()
    if notes and "excused" in notes.lower():
        return "Excused"
    if normalized == "present":
        return "Attended (Full)"
    if normalized in ("on_video_call", "late"):
        return "Attended (Partial)" if normalized == "on_video_call" else "Late Arrival"
    return "Missed"


@app.get("/api/online-activity/overview")
def get_online_activity_overview(limit: int = 20, db: Session = Depends(get_db_local)):
    """Return online activity data for coordinator and supervisor dashboards."""

    trainings = db.query(Training).order_by(Training.start_datetime.desc()).all()

    class_items = []
    meeting_items = []

    for training in trainings:
        participants = db.query(TrainingParticipant).filter(
            TrainingParticipant.training_id == training.id
        ).all()
        attendance_records = db.query(TrainingAttendance).filter(
            TrainingAttendance.training_id == training.id
        ).all()
        attendance_map = {record.attachee_id: record for record in attendance_records}
        target_list = meeting_items if _is_virtual_meeting(training) else class_items
        organizer = training.venue or "Training Team"

        for participant in participants:
            user = db.query(User).filter(User.id == participant.attachee_id).first()
            profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == participant.attachee_id).first()
            attendance = attendance_map.get(participant.attachee_id)

            target_list.append({
                "id": f"{training.id}-{participant.attachee_id}",
                "student_name": user.full_name if user else "Unknown",
                "student_id": profile.student_id if profile else "N/A",
                "title": training.title,
                "organizer": organizer,
                "date": training.start_datetime.isoformat() if training.start_datetime else None,
                "check_in": attendance.check_in_time.isoformat() if attendance and attendance.check_in_time else None,
                "status": _training_attendance_status(attendance.status if attendance else "absent", attendance.notes if attendance else ""),
                "notes": attendance.notes if attendance and attendance.notes else "",
                "category": "meeting" if _is_virtual_meeting(training) else "class"
            })

    recent_logs = db.query(SystemLog).filter(
        SystemLog.log_type.in_(["login", "security"])
    ).order_by(SystemLog.created_at.desc()).limit(limit).all()

    system_logs = []
    for log in recent_logs:
        user = db.query(User).filter(User.id == log.user_id).first()
        details = log.details or ""
        lowered = details.lower()
        if "successful" in lowered:
            action = "Login Successful"
        elif "failed" in lowered:
            action = "Failed Login Attempt"
        elif "timeout" in lowered:
            action = "Session Timeout"
        else:
            action = "Login Activity"

        system_logs.append({
            "id": log.id,
            "student_name": user.full_name if user else "System",
            "action": action,
            "ip_address": log.ip_address or "Unknown",
            "device": "Unknown device",
            "timestamp": log.created_at.isoformat() if log.created_at else None,
            "session_duration": "N/A",
            "details": details
        })

    return {
        "classes": class_items[:limit],
        "meetings": meeting_items[:limit],
        "system_logs": system_logs,
        "summary": {
            "classes_count": len(class_items),
            "meetings_count": len(meeting_items),
            "system_logs_count": len(system_logs),
        }
    }


@app.post("/api/trainings/attendance/{training_id}")
def save_training_attendance(
    training_id: int,
    attendance_data: dict,
    db: Session = Depends(get_db_local),
    # current_user: User = Depends(get_current_user)
):
    """Save attendance for a training session"""
    try:
        training = db.query(Training).filter(Training.id == training_id).first()
        if not training:
            raise HTTPException(status_code=404, detail="Training not found")
        
        # Clear existing attendance records for this training
        db.query(TrainingAttendance).filter(
            TrainingAttendance.training_id == training_id
        ).delete()
        
        # Save new attendance records
        status_map = {
            "Present âœ…": "present",
            "On Video Call ðŸ“¹": "on_video_call",
            "Late Arrival â°": "late",
            "Absent âŒ": "absent"
        }
        
        for attachee_id, record in attendance_data.items():
            status_text = record.get('status', 'Absent âŒ')
            status = status_map.get(status_text, "absent")
            
            attendance = TrainingAttendance(
                training_id=training_id,
                attachee_id=int(attachee_id),
                status=status,
                check_in_time=datetime.now(),
                notes=record.get('notes', ''),
                marked_by=1  # Replace with current_user.id
            )
            db.add(attendance)
        
        db.commit()
        
        return {"message": "Attendance saved successfully"}
        
    except Exception as e:
        db.rollback()
        print(f"Error saving attendance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/trainings/attendance/{training_id}")
def get_training_attendance(training_id: int, db: Session = Depends(get_db_local)):
    """Get attendance records for a training"""
    records = db.query(TrainingAttendance).filter(
        TrainingAttendance.training_id == training_id
    ).all()
    
    status_display = {
        "present": "Present âœ…",
        "on_video_call": "On Video Call ðŸ“¹",
        "late": "Late Arrival â°",
        "absent": "Absent âŒ"
    }
    
    result = {}
    for record in records:
        result[record.attachee_id] = {
            "status": status_display.get(record.status, "Absent âŒ"),
            "time": record.check_in_time.strftime("%H:%M") if record.check_in_time else "",
            "notes": record.notes or ""
        }
    
    return result


@app.get("/api/trainings/attendance/export/{training_id}")
def export_training_attendance(
    training_id: int,
    start_date: str = None,
    end_date: str = None,
    db: Session = Depends(get_db_local)
):
    """Export training attendance for date range"""
    query = db.query(TrainingAttendance).filter(
        TrainingAttendance.training_id == training_id
    )
    
    if start_date:
        start = datetime.fromisoformat(start_date).date()
        query = query.filter(TrainingAttendance.marked_at >= start)
    
    if end_date:
        end = datetime.fromisoformat(end_date).date()
        query = query.filter(TrainingAttendance.marked_at <= end)
    
    records = query.all()
    
    status_display = {
        "present": "Present",
        "on_video_call": "On Video Call",
        "late": "Late Arrival",
        "absent": "Absent"
    }
    
    result = []
    for record in records:
        user = db.query(User).filter(User.id == record.attachee_id).first()
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == record.attachee_id).first()
        
        result.append({
            "student_name": user.full_name if user else "Unknown",
            "student_id": profile.student_id if profile else "N/A",
            "status": status_display.get(record.status, "Absent"),
            "time": record.check_in_time.strftime("%H:%M") if record.check_in_time else "",
            "notes": record.notes or ""
        })
    
    return {"records": result}


@app.get("/api/trainings/participants/placed")
def get_placed_students_for_training(db: Session = Depends(get_db_local)):
    """Get all placed students for training invitations"""
    students = db.query(User).filter(User.role == "attachee").all()
    
    result = []
    for student in students:
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == student.id).first()
        if profile and profile.placement_status == "placed":
            result.append({
                "id": student.id,
                "full_name": student.full_name or student.username,
                "student_id": profile.student_id,
                "course": profile.course
            })
    
    return result

# ==================== SETTINGS & PROFILE MANAGEMENT ENDPOINTS ====================

@app.get("/api/users/profile/{user_id}")
def get_user_profile(user_id: int, db: Session = Depends(get_db_local)):
    """Get user profile with data from ALL related tables (User, AttacheeProfile, Contract, ApplicationForm)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get profile data
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == user.id).first()
    
    # Get contract data (most recent approved or filled contract)
    contract = db.query(Contract).filter(
        Contract.attachee_id == user.id,
        Contract.status.in_(["approved", "filled", "pending_supervisor", "sent"])
    ).order_by(Contract.created_at.desc()).first()
    
    # Get application form data
    application_form = db.query(ApplicationForm).filter(
        ApplicationForm.attachee_id == user.id,
        ApplicationForm.status == "completed"
    ).first()
    
    # Parse application form details if available
    personal_details = {}
    education_details = {}
    skills_details = {}
    experience_details = {}
    reference_details = {}
    
    if application_form:
        if application_form.personal_details:
            try:
                personal_details = json.loads(application_form.personal_details)
            except:
                pass
        if application_form.education_background:
            try:
                education_details = json.loads(application_form.education_background)
            except:
                pass
        if application_form.skills:
            try:
                skills_details = json.loads(application_form.skills)
            except:
                pass
        if application_form.experience:
            try:
                experience_details = json.loads(application_form.experience)
            except:
                pass
        if application_form.reference_details:
            try:
                reference_details = json.loads(application_form.reference_details)
            except:
                pass
    
    # Get supervisor information
    supervisor_info = None
    if profile and profile.assigned_supervisor_id:
        supervisor = db.query(User).filter(User.id == profile.assigned_supervisor_id).first()
        if supervisor:
            supervisor_info = {
                "id": supervisor.id,
                "name": supervisor.full_name
            }
    
    # ========== BUILD CONTRACT DETAILS OBJECT (COMPLETE) ==========
    contract_details = {}
    if contract:
        contract_details = {
            "contract_number": contract.contract_number,
            "full_name": contract.full_name,
            "id_number": contract.id_number,
            "mobile_phone_1": contract.mobile_phone_1,
            "mobile_phone_2": contract.mobile_phone_2,
            "school": contract.school,
            "course": contract.course,
            "level": contract.level,
            "start_date": contract.start_date.isoformat() if contract.start_date else None,
            "end_date": contract.end_date.isoformat() if contract.end_date else None,
            "school_supervisor": contract.school_supervisor,
            "school_supervisor_phone": contract.school_supervisor_phone,
            "parent_guardian": contract.parent_guardian,
            "parent_guardian_phone": contract.parent_guardian_phone,
            "email": contract.email,
            "mode": getattr(contract, 'mode', 'physical'),
            "total_fee": float(contract.total_fee) if contract.total_fee else 2950.00,
            "amount_paid": float(contract.amount_paid) if contract.amount_paid else 0,
            "payment_reference": contract.payment_reference,
            "payment_date": contract.payment_date.isoformat() if contract.payment_date else None,
            "status": contract.status,
            "signed_at": contract.signed_at.isoformat() if contract.signed_at else None,
            "filled_at": contract.filled_at.isoformat() if contract.filled_at else None,
            "completion_documents_fee": float(contract.completion_documents_fee) if contract.completion_documents_fee else 1550.00,
            # ========== COMPLETION PAYMENT FIELDS ==========
            "completion_paid": float(getattr(contract, 'completion_paid', 0)) if hasattr(contract, 'completion_paid') else 0,
            "completion_payment_reference": getattr(contract, 'completion_payment_reference', ''),
            "completion_payment_date": contract.completion_payment_date.isoformat() if hasattr(contract, 'completion_payment_date') and contract.completion_payment_date else None,
            # ========== ASSESSMENT PAYMENT FIELDS ==========
            "assessment_fee": float(getattr(contract, 'assessment_fee', 0)) if hasattr(contract, 'assessment_fee') else 0,
            "assessment_paid": float(getattr(contract, 'assessment_paid', 0)) if hasattr(contract, 'assessment_paid') else 0,
            "assessment_payment_reference": getattr(contract, 'assessment_payment_reference', ''),
            "assessment_payment_date": contract.assessment_payment_date.isoformat() if hasattr(contract, 'assessment_payment_date') and contract.assessment_payment_date else None,
            # ========== ACCOUNT DISABLE/EXTENSION FIELDS ==========
            "account_auto_disabled_at": user.account_auto_disabled_at.isoformat() if hasattr(user, 'account_auto_disabled_at') and user.account_auto_disabled_at else None,
            "payment_deadline_days": getattr(user, 'payment_deadline_days', 30) if hasattr(user, 'payment_deadline_days') else 30,
            "payment_deadline_extended_to": user.payment_deadline_extended_to.isoformat() if hasattr(user, 'payment_deadline_extended_to') and user.payment_deadline_extended_to else None,
            "contract_approved_at": user.contract_approved_at.isoformat() if hasattr(user, 'contract_approved_at') and user.contract_approved_at else None
        }
    
    # Build base profile data
    profile_data = {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name or personal_details.get('full_name', ''),
        "email": user.email or personal_details.get('email', ''),
        "role": user.role,
        "phone": user.phone or personal_details.get('mobile', ''),
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        
        # TRANSACTION VERIFICATION
        "transaction_verified": getattr(user, 'transaction_verified', False),
        "amount_paid": float(getattr(user, 'amount_paid', 0)) if getattr(user, 'amount_paid', 0) else 0,
        "transaction_verified_at": user.transaction_verified_at.isoformat() if getattr(user, 'transaction_verified_at', None) else None,
        "transaction_code": getattr(user, 'transaction_code', None),
        "payment_reference": getattr(user, 'payment_reference', None),
        
        # REFERENCE DETAILS
        "reference_details": reference_details,
        
        # CONTRACT DETAILS (CRITICAL FOR FRONTEND)
        "contract_details": contract_details
    }
    
    # Add role-specific data
    if user.role == "attachee":
        # Get assessment fee from contract or profile
        assessment_fee = 0
        assessment_paid = 0
        if contract and hasattr(contract, 'assessment_fee'):
            assessment_fee = float(contract.assessment_fee) if contract.assessment_fee else 0
            assessment_paid = float(contract.assessment_paid) if hasattr(contract, 'assessment_paid') and contract.assessment_paid else 0
        elif profile:
            assessment_fee = float(profile.assessment_fee) if hasattr(profile, 'assessment_fee') and profile.assessment_fee else 0
            assessment_paid = float(profile.assessment_paid) if hasattr(profile, 'assessment_paid') and profile.assessment_paid else 0
        
        profile_data["profile"] = {
            # Basic Info
            "student_id": profile.student_id if profile else personal_details.get('student_id', 'Not assigned'),
            "placement_status": profile.placement_status if profile else "not_applied",
            
            # Personal Details
            "date_of_birth": profile.date_of_birth.isoformat() if profile and profile.date_of_birth else personal_details.get('date_of_birth', None),
            "gender": profile.gender if profile else personal_details.get('gender', 'Not specified'),
            "id_number": personal_details.get('id_number', 'Not provided'),
            "county": profile.county if profile else personal_details.get('county', 'Not provided'),
            "address": profile.address or personal_details.get('physical_address', 'Not provided'),
            "postal_address": profile.postal_address or personal_details.get('postal_address', 'Not provided'),
            
            # Contact Info (from contract)
            "phone_alt": profile.phone_alt if profile else None,
            
            # Academic Information
            "institution": contract.school if contract else (education_details.get('institution') or (profile.institution if profile else 'Not provided')),
            "course": contract.course if contract else (education_details.get('course') or (profile.course if profile else 'Not provided')),
            "year_of_study": contract.level if contract else (education_details.get('year_of_study') or (profile.year_of_study if profile else 'Not provided')),
            "education_level": education_details.get('education_level', 'Not provided'),
            "academic_year": profile.academic_year if profile else education_details.get('academic_year', 'Not provided'),
            
            # Attachment Information
            "department": profile.department if profile else (contract.school_supervisor if contract else 'Not assigned'),
            "supervisor_id": profile.assigned_supervisor_id if profile else None,
            "supervisor": supervisor_info,
            
            # Dates
            "start_date": contract.start_date.isoformat() if contract and contract.start_date else (profile.start_date.isoformat() if profile and profile.start_date else None),
            "end_date": contract.end_date.isoformat() if contract and contract.end_date else (profile.end_date.isoformat() if profile and profile.end_date else None),
            
            # Skills and Experience
            "technical_skills": skills_details.get('technical_skills', 'Not provided'),
            "computer_skills": skills_details.get('computer_skills', 'Not provided'),
            "languages": skills_details.get('languages', 'Not provided'),
            "extracurricular": skills_details.get('extracurricular', 'Not provided'),
            "motivation": experience_details.get('motivation', 'Not provided'),
            "previous_experience": experience_details.get('previous_experience', 'Not provided'),
            
            # Application Form Submission
            "application_submitted_at": application_form.submitted_at.isoformat() if application_form else None,
            "application_status": application_form.status if application_form else "not_submitted",
            
            # ========== PAYMENT TRACKING FIELDS ==========
            "assessment_fee": assessment_fee,
            "assessment_paid": assessment_paid,
            "assessment_payment_reference": getattr(profile, 'assessment_payment_reference', '') if profile else '',
            "assessment_payment_date": profile.assessment_payment_date.isoformat() if profile and hasattr(profile, 'assessment_payment_date') and profile.assessment_payment_date else None,
            
            # Contract payment summary
            "attachment_total_fee": contract_details.get('total_fee', 0),
            "attachment_amount_paid": contract_details.get('amount_paid', 0),
            "completion_total_fee": contract_details.get('completion_documents_fee', 1550),
            "completion_amount_paid": contract_details.get('completion_paid', 0),
            
            # Account status
            "account_auto_disabled": user.account_auto_disabled_at is not None if hasattr(user, 'account_auto_disabled_at') else False,
            "payment_deadline_days": getattr(user, 'payment_deadline_days', 30) if hasattr(user, 'payment_deadline_days') else 30
        }
    elif user.role == "supervisor":
        sup_profile = db.query(SupervisorProfile).filter(SupervisorProfile.user_id == user.id).first()
        if sup_profile:
            profile_data["profile"] = {
                "department": sup_profile.department,
                "position": sup_profile.position,
                "employee_id": sup_profile.employee_id
            }
    elif user.role == "coordinator":
        coord_profile = db.query(CoordinatorProfile).filter(CoordinatorProfile.user_id == user.id).first()
        if coord_profile:
            profile_data["profile"] = {
                "department": coord_profile.department,
                "office_location": coord_profile.office_location,
                "position": coord_profile.position
            }
    
    return profile_data

@app.put("/api/users/update-profile/{user_id}")
def update_user_profile(user_id: int, data: dict, db: Session = Depends(get_db_local)):
    """Update user profile"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Update basic info
    if 'full_name' in data and data['full_name']:
        user.full_name = data['full_name']
    if 'email' in data and data['email']:
        user.email = data['email']
    if 'phone' in data:
        user.phone = data['phone']
    if 'username' in data and data['username']:
        # Check if username is taken
        existing = db.query(User).filter(
            User.username == data['username'],
            User.id != user_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Username already taken")
        user.username = data['username']
    
    # Update role-specific profile
    if user.role == 'coordinator':
        profile = db.query(CoordinatorProfile).filter(CoordinatorProfile.user_id == user_id).first()
        if not profile:
            profile = CoordinatorProfile(user_id=user_id)
            db.add(profile)
        
        if 'department' in data:
            profile.department = data['department']
        if 'position' in data:
            profile.position = data['position']
        if 'office_location' in data:
            profile.office_location = data['office_location']
            
    elif user.role == 'supervisor':
        profile = db.query(SupervisorProfile).filter(SupervisorProfile.user_id == user_id).first()
        if not profile:
            profile = SupervisorProfile(user_id=user_id)
            db.add(profile)
        
        if 'employee_id' in data:
            profile.employee_id = data['employee_id']
        if 'department' in data:
            profile.department = data['department']
        if 'position' in data:
            profile.position = data['position']
    
    db.commit()
    
    return {"message": "Profile updated successfully"}


@app.post("/api/users/change-password")
def change_password(data: dict, db: Session = Depends(get_db_local)):
    """Change user password"""
    user_id = data.get('user_id')
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    
    if not user_id or not current_password or not new_password:
        raise HTTPException(status_code=400, detail="Missing required fields")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Verify current password
    if not user.verify_password(current_password):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    
    # Validate new password strength
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    
    # Set new password
    user.set_password(new_password)
    user.password_set = True
    user.updated_at = datetime.now()
    
    db.commit()
    
    return {"message": "Password changed successfully"}


@app.post("/api/users/change-username")
def change_username(data: dict, db: Session = Depends(get_db_local)):
    """Change username"""
    user_id = data.get('user_id')
    current_password = data.get('current_password')
    new_username = data.get('new_username')
    
    if not user_id or not current_password or not new_username:
        raise HTTPException(status_code=400, detail="Missing required fields")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Verify password
    if not user.verify_password(current_password):
        raise HTTPException(status_code=401, detail="Password is incorrect")
    
    # Check if username is taken
    existing = db.query(User).filter(
        User.username == new_username,
        User.id != user_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already taken")
    
    user.username = new_username
    user.updated_at = datetime.now()
    db.commit()
    
    return {"message": "Username changed successfully", "new_username": new_username}


@app.get("/api/users/2fa-status/{user_id}")
def get_2fa_status(user_id: int, db: Session = Depends(get_db_local)):
    """Get 2FA status for user"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "enabled": getattr(user, 'two_factor_enabled', False),
        "method": getattr(user, 'two_factor_method', None)
    }


@app.post("/api/users/enable-2fa")
def enable_2fa(data: dict, db: Session = Depends(get_db_local)):
    """Enable two-factor authentication"""
    user_id = data.get('user_id')
    verification_code = data.get('verification_code')
    
    if not user_id or not verification_code:
        raise HTTPException(status_code=400, detail="Missing required fields")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # In production, verify the TOTP code here
    # For now, just enable 2FA
    user.two_factor_enabled = True
    user.two_factor_method = "authenticator"
    user.updated_at = datetime.now()
    db.commit()
    
    return {"message": "Two-factor authentication enabled successfully"}


@app.post("/api/users/disable-2fa")
def disable_2fa(data: dict, db: Session = Depends(get_db_local)):
    """Disable two-factor authentication"""
    user_id = data.get('user_id')
    password = data.get('password')
    
    if not user_id or not password:
        raise HTTPException(status_code=400, detail="Missing required fields")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Verify password
    if not user.verify_password(password):
        raise HTTPException(status_code=401, detail="Password is incorrect")
    
    user.two_factor_enabled = False
    user.two_factor_method = None
    user.updated_at = datetime.now()
    db.commit()
    
    return {"message": "Two-factor authentication disabled successfully"}


@app.post("/api/users/logout-all/{user_id}")
def logout_all_devices(user_id: int, db: Session = Depends(get_db_local)):
    """Logout from all other devices"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # In production, invalidate all session tokens for this user
    # For now, just return success
    user.last_logout_all = datetime.now()
    db.commit()
    
    return {"message": "Logged out from all other devices"}


# In main.py, add these endpoints:

@app.get("/api/users/sessions/{user_id}")
def get_user_sessions(user_id: int, request: FastAPIRequest, db: Session = Depends(get_db_local)):
    """Get all active sessions for a user"""
    # Get current session identifier from request
    current_session_id = request.headers.get("X-Session-Id", str(user_id))
    
    # Query active sessions from a sessions table
    # For now, return mock data
    sessions = [
        {
            "device": "Windows Desktop - Chrome",
            "location": "Nairobi, Kenya",
            "last_active": datetime.now().isoformat(),
            "is_current": True
        }
    ]
    
    return {"sessions": sessions}

@app.post("/api/users/logout-all/{user_id}")
def logout_all_devices(user_id: int, request: FastAPIRequest, db: Session = Depends(get_db_local)):
    """Logout from all other devices except current session"""
    current_session_id = request.headers.get("X-Session-Id", str(user_id))
    
    # Invalidate all sessions except current
    # Delete all session tokens for this user except current_session_id
    
    return {"message": "Logged out from all other devices", "sessions_terminated": 3}


@app.post("/api/users/preferences/{user_id}")
def save_preferences(user_id: int, data: dict, db: Session = Depends(get_db_local)):
    """Save user preferences"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Store preferences as JSON in user table or separate preferences table
    # For now, add a preferences column to User model or store in JSON field
    
    # Example: Store in a separate UserPreferences table
    # You'll need to create this table
    preferences = {
        "email_notifications": data.get('email_notifications', True),
        "desktop_notifications": data.get('desktop_notifications', True),
        "auto_refresh": data.get('auto_refresh', True),
        "language": data.get('language', 'en'),
        "theme": data.get('theme', 'light')
    }
    
    # In production, save to database
    # For now, just return success
    return {"message": "Preferences saved successfully"}


@app.get("/api/users/preferences/{user_id}")
def get_preferences(user_id: int, db: Session = Depends(get_db_local)):
    """Get user preferences"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # In production, load from database
    # For now, return default preferences
    return {
        "email_notifications": True,
        "desktop_notifications": True,
        "auto_refresh": True,
        "language": "en",
        "theme": "light"
    }


@app.post("/api/users/upload-avatar/{user_id}")
async def upload_avatar(
    user_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db_local)
):
    """Upload user avatar/profile picture"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Validate file type
    if not file.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail="Only image files are allowed")
    
    # Save file
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_filename = f"avatar_{user_id}_{timestamp}.jpg"
    file_path = Config.UPLOAD_DIR / safe_filename
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Update user profile picture URL
    user.profile_picture = str(file_path)
    db.commit()
    
    return {"message": "Avatar uploaded successfully", "file_path": str(file_path)}


@app.delete("/api/users/delete-account/{user_id}")
def delete_account(
    user_id: int,
    data: dict,
    db: Session = Depends(get_db_local)
):
    """Delete user account (requires password confirmation)"""
    password = data.get('password')
    
    if not password:
        raise HTTPException(status_code=400, detail="Password required for account deletion")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Verify password
    if not user.verify_password(password):
        raise HTTPException(status_code=401, detail="Incorrect password")
    
    # Soft delete or hard delete?
    # Option 1: Soft delete (deactivate)
    user.is_active = False
    user.email = f"deleted_{user.id}@deleted.com"
    user.username = f"deleted_{user.id}"
    
    db.commit()
    
    return {"message": "Account deactivated successfully"}


@app.post("/api/users/reactivate-account/{user_id}")
def reactivate_account(user_id: int, db: Session = Depends(get_db_local)):
    """Reactivate a deactivated account (admin only)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.is_active = True
    db.commit()
    
    return {"message": "Account reactivated successfully"}

# ==================== PLACEMENTS MANAGEMENT ENDPOINTS ====================

@app.get("/api/coordinator/students")
def get_all_students(db: Session = Depends(get_db_local)):
    """Get all attachees with their profile information"""
    students = db.query(User).filter(User.role == "attachee").all()
    
    result = []
    for student in students:
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == student.id).first()
        
        # Get contract amount if placed - get the most recent approved contract
        amount_paid = 0.00
        total_fee = 0.00
        mode = "physical"
        contract_number = None
        
        if profile and profile.placement_status == 'placed':
            # Get the most recent approved contract
            contract = db.query(Contract).filter(
                Contract.attachee_id == student.id,
                Contract.status == "approved"
            ).order_by(Contract.created_at.desc()).first()
            
            if contract:
                amount_paid = float(contract.amount_paid) if contract.amount_paid else 0.00
                total_fee = float(contract.total_fee) if hasattr(contract, 'total_fee') and contract.total_fee else 2950.00
                mode = getattr(contract, 'mode', 'physical')
                contract_number = contract.contract_number
            else:
                # If no approved contract, check for any contract
                any_contract = db.query(Contract).filter(
                    Contract.attachee_id == student.id
                ).order_by(Contract.created_at.desc()).first()
                if any_contract:
                    amount_paid = float(any_contract.amount_paid) if any_contract.amount_paid else 0.00
                    total_fee = float(any_contract.total_fee) if hasattr(any_contract, 'total_fee') and any_contract.total_fee else 2950.00
                    mode = getattr(any_contract, 'mode', 'physical')
                    contract_number = any_contract.contract_number
        
        # Get supervisor name if assigned
        supervisor_name = None
        if profile and profile.assigned_supervisor_id:
            supervisor = db.query(User).filter(User.id == profile.assigned_supervisor_id).first()
            if supervisor:
                supervisor_name = supervisor.full_name
        
        # Get contract mode and dates from contract if available
        start_date = None
        end_date = None
        
        if profile and profile.placement_status == 'placed':
            contract = db.query(Contract).filter(
                Contract.attachee_id == student.id,
                Contract.status == "approved"
            ).order_by(Contract.created_at.desc()).first()
            if contract:
                start_date = contract.start_date.isoformat() if contract.start_date else None
                end_date = contract.end_date.isoformat() if contract.end_date else None
            else:
                start_date = profile.start_date.isoformat() if profile and profile.start_date else None
                end_date = profile.end_date.isoformat() if profile and profile.end_date else None
        else:
            start_date = profile.start_date.isoformat() if profile and profile.start_date else None
            end_date = profile.end_date.isoformat() if profile and profile.end_date else None
        
        result.append({
            "id": student.id,
            "username": student.username,
            "full_name": student.full_name or student.username,
            "email": student.email,
            "phone": student.phone,
            "student_id": profile.student_id if profile else "N/A",
            "course": profile.course if profile else "N/A",
            "institution": profile.institution if profile else "N/A",
            "year_of_study": profile.year_of_study if profile else 1,
            "placement_status": profile.placement_status if profile else "not_applied",
            "department": profile.department if profile else "Not Assigned",
            "assigned_supervisor_id": profile.assigned_supervisor_id if profile else None,
            "supervisor_name": supervisor_name,
            "amount_paid": amount_paid,
            "total_fee": total_fee,
            "mode": mode,
            "contract_number": contract_number,
            "start_date": start_date,
            "end_date": end_date
        })
    
    return result


@app.delete("/api/coordinator/students/{student_id}")
def delete_coordinator_student(student_id: int, db: Session = Depends(get_db_local)):
    """Delete an attachee account and its related student records."""
    student = db.query(User).filter(User.id == student_id, User.role == "attachee").first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    reference_columns = {
        "user_id",
        "attachee_id",
        "target_user_id",
        "sender_id",
        "receiver_id",
        "assigned_to_id",
        "reviewed_by",
        "filled_by",
    }

    try:
        for table in reversed(Base.metadata.sorted_tables):
            if table.name == "users":
                continue

            matching_columns = [column for column in table.c if column.name in reference_columns]
            for column in matching_columns:
                db.execute(table.delete().where(column == student_id))

        db.delete(student)
        db.commit()
        return {"message": "Student account deleted successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete student: {str(e)}")


@app.put("/api/coordinator/placements/{student_id}")
def assign_placement(student_id: int, data: dict, db: Session = Depends(get_db_local)):
    """Assign a student to a department and supervisor"""
    
    # Get the student
    student = db.query(User).filter(User.id == student_id, User.role == "attachee").first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    # Get or create profile
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == student_id).first()
    if not profile:
        profile = AttacheeProfile(user_id=student_id)
        db.add(profile)
    
    # Update placement information
    department = data.get('department')
    supervisor_id = data.get('supervisor_id')
    start_date = data.get('start_date')
    notes = data.get('notes', '')
    
    if department:
        profile.department = department
    
    if supervisor_id:
        profile.assigned_supervisor_id = supervisor_id
    
    if start_date:
        try:
            profile.start_date = datetime.fromisoformat(start_date).date()
        except:
            pass
    
    # Update placement status
    profile.placement_status = "placed"
    
    # Check if there's an existing contract (filled by student)
    existing_contract = db.query(Contract).filter(
        Contract.attachee_id == student_id,
        Contract.status.in_(["filled", "pending_supervisor", "approved"])
    ).order_by(Contract.created_at.desc()).first()
    
    if existing_contract:
        # Use the existing contract's amount and update it to approved
        existing_contract.status = "approved"
        existing_contract.coordinator_approved = True
        existing_contract.supervisor_approved = True
        existing_contract.supervisor_id = supervisor_id if supervisor_id else existing_contract.supervisor_id
        existing_contract.signed_at = datetime.now()
        existing_contract.terms_agreed = True
        
        # Update dates if provided
        if start_date:
            try:
                existing_contract.start_date = datetime.fromisoformat(start_date).date()
            except:
                pass
        
        db.commit()
    else:
        # No existing contract - create a new one (for manual placement without contract form)
        # But don't hardcode amount - get from data or leave as 0
        amount_paid = data.get('amount_paid', 0.00)
        mode = data.get('mode', 'physical')
        total_fee = data.get('total_fee', 2950 if mode == 'physical' else 4950)
        
        contract_number = f"CTR-{datetime.now().strftime('%Y%m%d')}-{student_id}"
        contract = Contract(
            attachee_id=student_id,
            contract_number=contract_number,
            amount_paid=amount_paid,
            total_fee=total_fee,
            mode=mode,
            status="approved",
            coordinator_approved=True,
            supervisor_approved=True,
            supervisor_id=supervisor_id if supervisor_id else None,
            signed_at=datetime.now(),
            terms_agreed=True,
            start_date=datetime.fromisoformat(start_date).date() if start_date else None
        )
        db.add(contract)
    
    # Create notification for student
    notification = Notification(
        user_id=student_id,
        title="Placement Assigned!",
        message=f"You have been placed in {department}. Your supervisor will contact you soon.",
        type="placement"
    )
    db.add(notification)
    
    db.commit()
    
    # Get the final contract details for response
    final_contract = db.query(Contract).filter(
        Contract.attachee_id == student_id,
        Contract.status == "approved"
    ).order_by(Contract.created_at.desc()).first()
    
    return {
        "message": "Placement assigned successfully",
        "student_id": student_id,
        "department": department,
        "status": "placed",
        "contract_number": final_contract.contract_number if final_contract else None,
        "amount_paid": float(final_contract.amount_paid) if final_contract and final_contract.amount_paid else 0.00,
        "total_fee": float(final_contract.total_fee) if final_contract and hasattr(final_contract, 'total_fee') else 2950.00,
        "mode": getattr(final_contract, 'mode', 'physical') if final_contract else 'physical'
    }


@app.get("/api/coordinator/placements/statistics")
def get_placement_statistics(db: Session = Depends(get_db_local)):
    """Get placement statistics with actual fees from contracts"""
    
    # Get all attachees
    all_students = db.query(User).filter(User.role == "attachee").count()
    
    # Get placed students
    placed_students = db.query(AttacheeProfile).filter(
        AttacheeProfile.placement_status == "placed"
    ).count()
    
    # Get pending placements (approved but not placed)
    pending_placements = db.query(AttacheeProfile).filter(
        AttacheeProfile.placement_status == "approved"
    ).count()
    
    # Calculate total fees collected from approved contracts
    # Get all approved contracts for placed students
    approved_contracts = db.query(Contract).filter(
        Contract.status == "approved"
    ).all()
    
    total_fees = 0.00
    for contract in approved_contracts:
        # Get the attachee profile to check if they are placed
        profile = db.query(AttacheeProfile).filter(
            AttacheeProfile.user_id == contract.attachee_id
        ).first()
        
        if profile and profile.placement_status == "placed":
            # Add the amount paid from the contract
            if contract.amount_paid:
                total_fees += float(contract.amount_paid)
    
    # Alternative calculation using sum aggregate (more efficient)
    # total_fees = db.query(func.sum(Contract.amount_paid)).filter(
    #     Contract.status == "approved"
    # ).scalar() or 0
    
    # Calculate total expected fees (based on mode)
    total_expected_fees = 0.00
    for contract in approved_contracts:
        profile = db.query(AttacheeProfile).filter(
            AttacheeProfile.user_id == contract.attachee_id
        ).first()
        
        if profile and profile.placement_status == "placed":
            mode = getattr(contract, 'mode', 'physical')
            expected_fee = 4950.00 if mode == 'online' else 2950.00
            total_expected_fees += expected_fee
    
    # Calculate outstanding balance
    outstanding_balance = total_expected_fees - total_fees
    
    # Calculate average payment per placed student
    average_payment = total_fees / placed_students if placed_students > 0 else 0
    
    return {
        "total_students": all_students,
        "placed_students": placed_students,
        "pending_placements": pending_placements,
        "total_fees_collected": round(total_fees, 2),
        "total_expected_fees": round(total_expected_fees, 2),
        "outstanding_balance": round(outstanding_balance, 2),
        "average_payment": round(average_payment, 2)
    }


@app.get("/api/coordinator/placements/{student_id}")
def get_placement_details(student_id: int, db: Session = Depends(get_db_local)):
    """Get detailed placement information for a student"""
    
    student = db.query(User).filter(User.id == student_id, User.role == "attachee").first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == student_id).first()
    
    # Get the most recent contract (approved, filled, or pending)
    contract = db.query(Contract).filter(
        Contract.attachee_id == student_id
    ).order_by(Contract.created_at.desc()).first()
    
    # Get supervisor info
    supervisor_info = None
    if profile and profile.assigned_supervisor_id:
        supervisor = db.query(User).filter(User.id == profile.assigned_supervisor_id).first()
        if supervisor:
            sup_profile = db.query(SupervisorProfile).filter(SupervisorProfile.user_id == supervisor.id).first()
            supervisor_info = {
                "id": supervisor.id,
                "name": supervisor.full_name,
                "department": sup_profile.department if sup_profile else None,
                "position": sup_profile.position if sup_profile else None,
                "employee_id": sup_profile.employee_id if sup_profile else None
            }
    
    # Get contract details
    contract_details = None
    if contract:
        # Calculate balance if total_fee exists
        total_fee = float(contract.total_fee) if hasattr(contract, 'total_fee') and contract.total_fee else 0
        amount_paid = float(contract.amount_paid) if contract.amount_paid else 0
        balance = total_fee - amount_paid if total_fee > 0 else 0
        
        contract_details = {
            "contract_number": contract.contract_number,
            "status": contract.status,
            "mode": getattr(contract, 'mode', 'physical'),
            "total_fee": total_fee,
            "amount_paid": amount_paid,
            "balance": balance,
            "payment_reference": contract.payment_reference,
            "payment_date": contract.payment_date.isoformat() if contract.payment_date else None,
            "signed_at": contract.signed_at.isoformat() if contract.signed_at else None,
            "filled_at": contract.filled_at.isoformat() if contract.filled_at else None,
            "terms_agreed": contract.terms_agreed,
            # Contract filled data
            "id_number": contract.id_number,
            "mobile_phone_1": contract.mobile_phone_1,
            "mobile_phone_2": contract.mobile_phone_2,
            "email": contract.email,
            "school": contract.school,
            "course": contract.course,
            "level": contract.level,
            "start_date": contract.start_date.isoformat() if contract.start_date else None,
            "end_date": contract.end_date.isoformat() if contract.end_date else None,
            "school_supervisor": contract.school_supervisor,
            "school_supervisor_phone": contract.school_supervisor_phone,
            "parent_guardian": contract.parent_guardian,
            "parent_guardian_phone": contract.parent_guardian_phone
        }
    else:
        contract_details = {
            "contract_number": None,
            "status": "not_created",
            "mode": "not_set",
            "total_fee": 0,
            "amount_paid": 0,
            "balance": 0,
            "payment_reference": None,
            "payment_date": None,
            "signed_at": None,
            "filled_at": None,
            "terms_agreed": False
        }
    
    # Get placement dates from contract if available, otherwise from profile
    start_date = None
    end_date = None
    if contract and contract.start_date:
        start_date = contract.start_date.isoformat()
    elif profile and profile.start_date:
        start_date = profile.start_date.isoformat()
    
    if contract and contract.end_date:
        end_date = contract.end_date.isoformat()
    elif profile and profile.end_date:
        end_date = profile.end_date.isoformat()
    
    return {
        "student": {
            "id": student.id,
            "name": student.full_name or student.username,
            "student_id": profile.student_id if profile else "N/A",
            "course": profile.course if profile else "N/A",
            "institution": profile.institution if profile else "N/A",
            "email": student.email,
            "phone": student.phone
        },
        "placement": {
            "department": profile.department if profile else "Not Assigned",
            "start_date": start_date,
            "end_date": end_date,
            "status": profile.placement_status if profile else "not_applied"
        },
        "contract": contract_details,
        "supervisor": supervisor_info
    }


@app.put("/api/coordinator/placements/{student_id}/department")
def update_student_department(student_id: int, data: dict, db: Session = Depends(get_db_local)):
    """Update only the department for a student"""
    
    student = db.query(User).filter(User.id == student_id, User.role == "attachee").first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == student_id).first()
    if not profile:
        profile = AttacheeProfile(user_id=student_id)
        db.add(profile)
    
    new_department = data.get('department')
    if new_department:
        profile.department = new_department
    
    db.commit()
    
    return {"message": f"Department updated to {new_department}"}


@app.put("/api/coordinator/placements/{student_id}/supervisor")
def update_student_supervisor(student_id: int, data: dict, db: Session = Depends(get_db_local)):
    """Update the supervisor for a student"""
    
    student = db.query(User).filter(User.id == student_id, User.role == "attachee").first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == student_id).first()
    if not profile:
        profile = AttacheeProfile(user_id=student_id)
        db.add(profile)
    
    supervisor_id = data.get('supervisor_id')
    if supervisor_id:
        # Verify supervisor exists
        supervisor = db.query(User).filter(User.id == supervisor_id, User.role == "supervisor").first()
        if not supervisor:
            raise HTTPException(status_code=404, detail="Supervisor not found")
        
        profile.assigned_supervisor_id = supervisor_id
        
        # Also update contract supervisor
        contract = db.query(Contract).filter(
            Contract.attachee_id == student_id,
            Contract.status == "approved"
        ).first()
        if contract:
            contract.supervisor_id = supervisor_id
    
    db.commit()
    
    return {"message": "Supervisor assigned successfully"}

@app.get("/api/coordinator/overtime-requests")
def get_overtime_requests(db: Session = Depends(get_db_local)):
    """Get pending overtime requests from students"""
    # Query overtime requests from ApplicationForm table
    forms = db.query(ApplicationForm).filter(
        ApplicationForm.overtime_requested == True,
        ApplicationForm.overtime_approved == False,
        ApplicationForm.status == "in_progress"
    ).all()
    
    result = []
    for form in forms:
        user = db.query(User).filter(User.id == form.attachee_id).first()
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == form.attachee_id).first()
        
        # Use created_at instead of updated_at (which doesn't exist)
        requested_at = form.session_start if form.session_start else datetime.now()
        
        result.append({
            "id": form.id,
            "student_name": user.full_name if user else "Unknown",
            "student_id": profile.student_id if profile else "N/A",
            "requested_minutes": form.overtime_minutes if form.overtime_minutes else 5,
            "requested_at": requested_at.isoformat(),
            "session_expiry": form.session_expiry.isoformat() if form.session_expiry else "N/A",
            "form_title": "Application Form",
            "status": "pending"
        })
    
    return result

# ==================== MANUAL ATTENDANCE REQUEST ENDPOINTS ====================

@app.post("/api/attachee/attendance/request-manual")
def request_manual_attendance(
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Student requests manual check-in/out (sent to coordinator for approval)"""
    
    user_id = data.get('user_id')
    action = data.get('action')  # 'checkin' or 'checkout'
    reason = data.get('reason', '')
    
    if not user_id or not action:
        raise HTTPException(status_code=400, detail="user_id and action are required")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == user_id).first()
    
    # Create a notification for all coordinators
    coordinators = db.query(User).filter(User.role == "coordinator").all()
    
    for coord in coordinators:
        notification = Notification(
            user_id=coord.id,
            title=f"ðŸ“‹ Manual {action.capitalize()} Request",
            message=f"Student {user.full_name} ({profile.student_id if profile else 'N/A'}) requests manual {action}. Reason: {reason}",
            type="attendance_request",
            is_read=False
        )
        db.add(notification)

    db.commit()
    
    # Send push notifications to coordinators
    for coord in coordinators:
        background_tasks.add_task(
            send_push_notification,
            coord.id,
            f"ðŸ“‹ Manual {action.capitalize()} Request",
            f"Student {user.full_name} requests manual {action}"
        )
    
    return {
        "message": f"Manual {action} request sent to coordinator for approval",
        "status": "pending"
    }




@app.post("/api/coordinator/attendance/reject-manual")
def reject_manual_attendance(
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Coordinator rejects manual check-in/out request"""
    
    user_id = data.get('user_id')
    action = data.get('action')
    request_id = data.get('request_id')
    reason = data.get('reason', '')
    
    if not user_id or not action:
        raise HTTPException(status_code=400, detail="user_id and action are required")
    
    # Mark the notification as read
    if request_id:
        notification = db.query(Notification).filter(Notification.id == request_id).first()
        if notification:
            notification.is_read = True
    
    db.commit()
    
    # Notify student
    background_tasks.add_task(
        send_push_notification,
        user_id,
        f"âŒ Manual {action.capitalize()} Rejected",
        f"Your manual {action} request has been rejected. Reason: {reason}" if reason else f"Your manual {action} request has been rejected."
    )
    
    # Create notification for student
    student_notification = Notification(
        user_id=user_id,
        title=f"Manual {action.capitalize()} Rejected",
        message=f"Your manual {action} request has been rejected. Reason: {reason}" if reason else f"Your manual {action} request has been rejected.",
        type="attendance_rejection"
    )
    db.add(student_notification)
    db.commit()
    
    return {"message": f"Manual {action} rejected successfully"}


@app.get("/api/attachee/attendance/manual-status/{user_id}")
def get_manual_attendance_status(
    user_id: int,
    db: Session = Depends(get_db_local)
):
    """Get status of manual attendance requests for a student"""
    
    today = date.today()
    
    # Check if there's any attendance record for today
    attendance = db.query(Attendance).filter(
        Attendance.attachee_id == user_id,
        Attendance.date == today
    ).first()
    
    # If there's an attendance record with check-in or check-out, it was processed
    if attendance and (attendance.check_in_time or attendance.check_out_time):
        # Check if it was a manual entry
        if attendance.remarks and "manual" in attendance.remarks.lower():
            return {
                "has_recent_request": True,
                "status": "approved",
                "message": f"Manual attendance approved at {attendance.check_in_time or attendance.check_out_time}",
                "timestamp": datetime.now().isoformat()
            }
    
    # Check for pending manual request notification
    pending = db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.type == "attendance_request",
        Notification.is_read == False
    ).first()
    
    if pending:
        return {
            "has_recent_request": True,
            "status": "pending",
            "message": pending.message,
            "timestamp": pending.created_at.isoformat()
        }
    
    # Check for approved notification
    approved = db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.type == "attendance_approval"
    ).order_by(Notification.created_at.desc()).first()
    
    if approved:
        return {
            "has_recent_request": True,
            "status": "approved",
            "message": approved.message,
            "timestamp": approved.created_at.isoformat()
        }
    
    return {
        "has_recent_request": False,
        "status": None,
        "message": None
    }

@app.post("/api/coordinator/application-form/{form_id}/review")
def review_application_form(
    form_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Review an application form (approve/reject)"""
    return process_application_form_review(form_id, data, db, background_tasks)


@app.post("/api/supervisor/application-form/{form_id}/review")
def supervisor_review_application_form(
    form_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Supervisor application review is no longer allowed."""
    raise HTTPException(
        status_code=403,
        detail="Application review is handled by the coordinator only."
    )

@app.post("/api/application-form/approve-overtime/{form_id}")
def approve_overtime(form_id: int, approved: bool, background_tasks: BackgroundTasks, db: Session = Depends(get_db_local)):
    """Coordinator approves or rejects overtime request"""
    form = db.query(ApplicationForm).filter(ApplicationForm.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")
    
    if approved:
        form.session_expiry = form.session_expiry + timedelta(minutes=form.overtime_minutes)
        form.overtime_approved = True
        message = f"Overtime approved. Extended by {form.overtime_minutes} minutes."
        
        # âœ… SEND NOTIFICATION TO STUDENT
        background_tasks.add_task(
            send_push_notification,
            form.attachee_id,
            "â° Overtime Approved",
            f"Your request for {form.overtime_minutes} minutes extension has been approved!"
        )
    else:
        form.overtime_approved = False
        message = "Overtime request denied."
        
        # âœ… SEND REJECTION NOTIFICATION
        background_tasks.add_task(
            send_push_notification,
            form.attachee_id,
            "â° Overtime Denied",
            "Your overtime request was not approved. Please submit your form before time expires."
        )
    
    db.commit()
    
    # âœ… NOTIFY COORDINATOR THAT REQUEST WAS PROCESSED
    coordinators = db.query(User).filter(User.role == "coordinator").all()
    for coord in coordinators:
        notification = Notification(
            user_id=coord.id,
            title="Overtime Request Processed",
            message=f"Overtime request for student ID {form.attachee_id} has been { 'approved' if approved else 'rejected' }.",
            type="overtime"
        )
        db.add(notification)
    db.commit()
    
    return {"message": message}

@app.get("/api/coordinator/manual-attendance-requests")
def get_manual_attendance_requests(
    db: Session = Depends(get_db_local)
):
    """Get all pending manual attendance requests for coordinator"""
    
    # Get all unread attendance request notifications
    notifications = db.query(Notification).filter(
        Notification.type == "attendance_request",
        Notification.is_read == False
    ).order_by(Notification.created_at.desc()).all()
    
    result = []
    for notif in notifications:
        # Extract student info from message
        message = notif.message
        student_name = "Unknown"
        student_id = "N/A"
        actual_user_id = None
        action = "checkin"
        reason = ""
        
        # Parse message to extract actual user_id
        import re
        
        # Look for student ID pattern
        id_match = re.search(r'\(([^)]+)\)', message)
        if id_match:
            student_identifier = id_match.group(1)
            # Try to find user by student_id
            profile = db.query(AttacheeProfile).filter(
                AttacheeProfile.student_id == student_identifier
            ).first()
            if profile:
                actual_user_id = profile.user_id
                student_id = student_identifier
                user = db.query(User).filter(User.id == actual_user_id).first()
                if user:
                    student_name = user.full_name or user.username
            else:
                # Try by username
                user = db.query(User).filter(User.username == student_identifier).first()
                if user:
                    actual_user_id = user.id
                    student_name = user.full_name or user.username
                    student_id = student_identifier
        
        # Extract action
        if "checkin" in message.lower():
            action = "checkin"
        elif "checkout" in message.lower():
            action = "checkout"
        
        # Extract reason
        reason_match = re.search(r'Reason: (.+)', message)
        if reason_match:
            reason = reason_match.group(1)
        
        if actual_user_id:
            result.append({
                "id": notif.id,
                "request_id": notif.id,
                "user_id": actual_user_id,  # This is the important field!
                "student_name": student_name,
                "student_id": student_id,
                "action": action,
                "reason": reason,
                "requested_at": notif.created_at.isoformat(),
                "status": "pending"
            })
        else:
            print(f"âš ï¸ Could not extract user_id from notification {notif.id}: {message}")

    return result


@app.post("/api/coordinator/attendance/approve-manual")
def approve_manual_attendance(
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Coordinator approves manual check-in/out request"""
    
    user_id = data.get('user_id')
    action = data.get('action')
    request_id = data.get('request_id')
    reason = data.get('reason', '')
    
    print(f"ðŸ“‹ Approving manual attendance - user_id: {user_id}, action: {action}, request_id: {request_id}")
    
    if not user_id or not action:
        raise HTTPException(status_code=400, detail="user_id and action are required")
    
    # CRITICAL FIX: If user_id is 1 or invalid, try to get it from the notification
    if user_id == 1 or user_id is None:
        # Try to get the actual user_id from the notification
        if request_id:
            notification = db.query(Notification).filter(Notification.id == request_id).first()
            if notification:
                # Extract user_id from notification message or get the notification's user_id
                # Note: The notification's user_id is the coordinator, not the student
                # So we need to parse the message to get the student ID
                message = notification.message
                import re
                # Look for patterns like "Student X (MFB000001)" or similar
                student_match = re.search(r'Student .+? \(([^)]+)\)', message)
                if student_match:
                    student_identifier = student_match.group(1)
                    # Try to find user by student_id or username
                    profile = db.query(AttacheeProfile).filter(
                        AttacheeProfile.student_id == student_identifier
                    ).first()
                    if profile:
                        user_id = profile.user_id
                        print(f"ðŸ” Found actual user_id from notification: {user_id} (Student ID: {student_identifier})")
                    else:
                        # Try by username
                        user = db.query(User).filter(User.username == student_identifier).first()
                        if user:
                            user_id = user.id
                            print(f"ðŸ” Found actual user_id from username: {user_id}")
    
    # Validate user exists
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    
    today = date.today()
    current_time = datetime.now().time()
    
    # Get or create attendance record
    attendance = db.query(Attendance).filter(
        Attendance.attachee_id == user_id,
        Attendance.date == today
    ).first()
    
    if not attendance:
        attendance = Attendance(
            attachee_id=user_id,
            date=today
        )
        db.add(attendance)
        db.flush()
        print(f"ðŸ“ Created new attendance record for user {user_id}: {attendance.id}")
    
    # Update based on action
    if action == 'checkin':
        attendance.check_in_time = current_time
        attendance.status = "present"
        attendance.remarks = f"Manual check-in approved by coordinator. Reason: {reason}" if reason else "Manual check-in approved by coordinator"
        print(f"âœ… Set check-in time to {current_time} for user {user_id}")
    elif action == 'checkout':
        if not attendance.check_in_time:
            # If no check-in time, set a default check-in time (e.g., 9:00 AM)
            default_checkin = datetime.now().replace(hour=7, minute=30, second=0).time()
            attendance.check_in_time = default_checkin
            print(f"âš ï¸ No check-in found for user {user_id}, set default check-in time to {default_checkin}")
        
        attendance.check_out_time = current_time
        if not attendance.status:
            attendance.status = "present"
        attendance.remarks = f"Manual check-out approved by coordinator. Reason: {reason}" if reason else "Manual check-out approved by coordinator"
        print(f"âœ… Set check-out time to {current_time} for user {user_id}")
    else:
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}")
    
    db.commit()
    print(f"ðŸ’¾ Attendance record {attendance.id} saved for user {user_id}")
    
    # Mark the original request notification as read
    if request_id:
        notif = db.query(Notification).filter(Notification.id == request_id).first()
        if notif:
            notif.is_read = True
            db.commit()
            print(f"ðŸ“ Marked request notification {request_id} as read")
    
    # Create approval notification for the student
    approval_notification = Notification(
        user_id=user_id,
        title=f"âœ… Manual {action.capitalize()} Approved",
        message=f"Your manual {action} request has been approved. You have been {action} at {current_time.strftime('%H:%M:%S')}.",
        type="attendance_approval",
        is_read=False
    )
    db.add(approval_notification)
    db.commit()
    print(f"ðŸ“ Created approval notification for student {user_id}")
    
    # Send push notification if available
    try:
        send_push_notification(
            user_id,
            f"âœ… Manual {action.capitalize()} Approved",
            f"Your manual {action} request has been approved at {current_time.strftime('%H:%M:%S')}."
        )
    except Exception as e:
        print(f"âš ï¸ Push notification error: {e}")
    
    return {"message": f"Manual {action} approved successfully", "user_id": user_id}
    

@app.post("/api/coordinator/attendance/reject-manual")
def reject_manual_attendance(data: dict, db: Session = Depends(get_db_local)):
    """Reject manual attendance request"""
    user_id = data.get('user_id')
    action = data.get('action')
    request_id = data.get('request_id')
    reason = data.get('reason', '')
    
    # Mark notification as read
    notification = db.query(Notification).filter(Notification.id == request_id).first()
    if notification:
        notification.is_read = True
    
    db.commit()
    
    # Notify student
    send_push_notification(user_id, "âŒ Manual Attendance Rejected", f"Your manual {action} request was rejected. Reason: {reason}")

    return {"message": f"Manual {action} rejected successfully"}

from collections import defaultdict
from datetime import datetime, timedelta

# Rate limiting for face verification
verification_attempts = defaultdict(list)

def check_rate_limit(user_id: int) -> tuple[bool, str]:
    """Check if user has exceeded verification attempts"""
    now = datetime.now()
    # Clean old attempts (older than 15 minutes)
    verification_attempts[user_id] = [
        attempt for attempt in verification_attempts[user_id] 
        if attempt > now - timedelta(minutes=15)
    ]
    
    # Max 5 attempts per 15 minutes
    if len(verification_attempts[user_id]) >= 5:
        return False, "Too many verification attempts. Please wait 15 minutes or use manual check-in."
    
    verification_attempts[user_id].append(now)
    return True, ""

    # Add rate limiting to verify_face endpoint
    # Add this at the beginning of the verify_face function:
    allowed, message = check_rate_limit(user_id)
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"success": False, "message": message}
        )

# Add to imports
from contract_pdf import ContractPDFGenerator
import json
from fastapi.responses import FileResponse

# ==================== CONTRACT MANAGEMENT ENDPOINTS ====================

@app.post("/api/contracts/create-for-attachee")
def create_contract_for_attachee(
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Coordinator creates a contract for a specific attachee"""
    
    attachee_id = data.get('attachee_id')
    coordinator_id = data.get('coordinator_id')
    
    # Get attachee details
    attachee = db.query(User).filter(User.id == attachee_id, User.role == "attachee").first()
    if not attachee:
        raise HTTPException(status_code=404, detail="Attachee not found")
    
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == attachee_id).first()
    
    # Generate contract number
    contract_number = f"CTR-{datetime.now().strftime('%Y%m%d')}-{attachee_id}"
    
    # Create contract
    contract = Contract(
        attachee_id=attachee_id,
        contract_number=contract_number,
        full_name=attachee.full_name,
        id_number=data.get('id_number', ''),
        mobile_phone_1=data.get('mobile_phone_1', attachee.phone),
        mobile_phone_2=data.get('mobile_phone_2', ''),
        school=data.get('school', profile.institution if profile else ''),
        course=data.get('course', profile.course if profile else ''),
        level=data.get('level', f"Year {profile.year_of_study if profile else 1}"),
        start_date=datetime.fromisoformat(data.get('start_date')).date() if data.get('start_date') else None,
        end_date=datetime.fromisoformat(data.get('end_date')).date() if data.get('end_date') else None,
        school_supervisor=data.get('school_supervisor', ''),
        school_supervisor_phone=data.get('school_supervisor_phone', ''),
        parent_guardian=data.get('parent_guardian', ''),
        parent_guardian_phone=data.get('parent_guardian_phone', ''),
        email=attachee.email,
        amount_paid=data.get('amount_paid', 0),
        payment_reference=data.get('payment_reference', ''),
        payment_date=datetime.now() if data.get('amount_paid', 0) > 0 else None,
        status="pending_attachee",
        created_by=coordinator_id,
        created_at=datetime.now()
    )
    
    db.add(contract)
    db.commit()
    db.refresh(contract)
    
    # Generate PDF contract
    try:
        generator = ContractPDFGenerator()
        contract_data = {
            "contract_number": contract.contract_number,
            "full_name": contract.full_name,
            "id_number": contract.id_number,
            "mobile_phone_1": contract.mobile_phone_1,
            "mobile_phone_2": contract.mobile_phone_2,
            "email": contract.email,
            "school": contract.school,
            "course": contract.course,
            "level": contract.level,
            "start_date": contract.start_date.strftime("%B %d, %Y") if contract.start_date else "_________",
            "end_date": contract.end_date.strftime("%B %d, %Y") if contract.end_date else "_________",
            "school_supervisor": contract.school_supervisor,
            "school_supervisor_phone": contract.school_supervisor_phone,
            "parent_guardian": contract.parent_guardian,
            "parent_guardian_phone": contract.parent_guardian_phone,
            "completion_documents_fee": 1550.00,
            "amount_paid": contract.amount_paid,
            "payment_reference": contract.payment_reference or "Pending"
        }
        pdf_path = generator.generate_contract(contract_data)
        contract.pdf_path = pdf_path
        db.commit()
    except Exception as e:
        print(f"Error generating PDF: {e}")
    
    # Notify attachee
    background_tasks.add_task(
        send_push_notification,
        attachee_id,
        "ðŸ“ Contract Ready for Signing",
        f"Your contract (No: {contract_number}) is ready for review and signature."
    )
    
    notification = Notification(
        user_id=attachee_id,
        title="Contract Ready",
        message=f"Please review and sign your attachment contract (No: {contract_number})",
        type="contract"
    )
    db.add(notification)
    db.commit()
    
    return {
        "message": "Contract created successfully",
        "contract_id": contract.id,
        "contract_number": contract_number
    }


@app.get("/api/attachee/contracts/{attachee_id}")
def get_attachee_contracts(attachee_id: int, db: Session = Depends(get_db_local)):
    """Get contracts for an attachee with filled data"""
    contracts = db.query(Contract).filter(
        Contract.attachee_id == attachee_id
    ).order_by(Contract.created_at.desc()).all()
    
    result = []
    for contract in contracts:
        result.append({
            "id": contract.id,
            "contract_number": contract.contract_number,
            "status": contract.status,
            "created_at": contract.created_at.isoformat(),
            "signed_at": contract.signed_at.isoformat() if contract.signed_at else None,
            "filled_at": contract.filled_at.isoformat() if contract.filled_at else None,
            "pdf_path": contract.pdf_path,
            "amount_paid": float(contract.amount_paid) if contract.amount_paid else 0,
            "total_fee": getattr(contract, 'total_fee', 2950),
            "mode": getattr(contract, 'mode', 'physical'),
            "rejection_reason": contract.rejection_reason or "",
            "supervisor_notes": contract.supervisor_notes or "",
            "revision_count": contract.revision_count or 0,
            "last_revision_at": contract.last_revision_at.isoformat() if contract.last_revision_at else None,
            # Filled data
            "full_name": contract.full_name,
            "id_number": contract.id_number,
            "mobile_phone_1": contract.mobile_phone_1,
            "mobile_phone_2": contract.mobile_phone_2,
            "email": contract.email,
            "school": contract.school,
            "course": contract.course,
            "level": contract.level,
            "start_date": contract.start_date.isoformat() if contract.start_date else None,
            "end_date": contract.end_date.isoformat() if contract.end_date else None,
            "school_supervisor": contract.school_supervisor,
            "school_supervisor_phone": contract.school_supervisor_phone,
            "parent_guardian": contract.parent_guardian,
            "parent_guardian_phone": contract.parent_guardian_phone,
            "terms_agreed": contract.terms_agreed
        })
    
    return result

@app.post("/api/contracts/sign/{contract_id}")
def sign_contract(
    contract_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Attachee signs the contract (checkbox agreement)"""
    
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    
    terms_agreed = data.get('terms_agreed', False)
    
    if not terms_agreed:
        raise HTTPException(status_code=400, detail="You must agree to the terms and conditions")
    
    # Update contract with signature
    contract.terms_agreed = True
    contract.signed_by = contract.full_name
    contract.signed_at = datetime.now()
    contract.status = "pending_supervisor"
    contract.updated_at = datetime.now()
    
    db.commit()
    
    # Notify coordinators
    coordinators = db.query(User).filter(User.role == "coordinator").all()
    for coord in coordinators:
        background_tasks.add_task(
            send_push_notification,
            coord.id,
            "ðŸ“ Contract Signed",
            f"Attachee {contract.full_name} has signed the contract (No: {contract.contract_number})"
        )
        
        notification = Notification(
            user_id=coord.id,
            title="Contract Signed",
            message=f"Attachee {contract.full_name} has signed the contract. Pending supervisor approval.",
            type="contract"
        )
        db.add(notification)
    
    db.commit()
    
    return {"message": "Contract signed successfully", "status": "pending_supervisor"}



@app.get("/api/contracts/download/{contract_id}")
def download_contract(contract_id: int, db: Session = Depends(get_db_local)):
    """Download contract PDF"""
    
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    
    if not contract.pdf_path or not os.path.exists(contract.pdf_path):
        # Generate PDF if missing
        try:
            generator = ContractPDFGenerator()
            contract_data = {
                "contract_number": contract.contract_number,
                "full_name": contract.full_name,
                "id_number": contract.id_number,
                "mobile_phone_1": contract.mobile_phone_1,
                "mobile_phone_2": contract.mobile_phone_2,
                "email": contract.email,
                "school": contract.school,
                "course": contract.course,
                "level": contract.level,
                "start_date": contract.start_date.strftime("%B %d, %Y") if contract.start_date else "_________",
                "end_date": contract.end_date.strftime("%B %d, %Y") if contract.end_date else "_________",
                "school_supervisor": contract.school_supervisor,
                "school_supervisor_phone": contract.school_supervisor_phone,
                "parent_guardian": contract.parent_guardian,
                "parent_guardian_phone": contract.parent_guardian_phone,
                "completion_documents_fee": 1550.00,
                "amount_paid": float(contract.amount_paid) if contract.amount_paid else 0,
                "payment_reference": contract.payment_reference or "Pending"
            }
            pdf_path = generator.generate_contract(contract_data)
            contract.pdf_path = pdf_path
            db.commit()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error generating PDF: {str(e)}")
    
    return FileResponse(
        contract.pdf_path,
        media_type='application/pdf',
        filename=f"Contract_{contract.contract_number}.pdf"
    )

# Add these endpoints to main.py

@app.post("/api/contracts/remind/{contract_id}")
def remind_attachee(contract_id: int, db: Session = Depends(get_db_local)):
    """Send reminder to attachee to sign contract"""
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    
    send_push_notification(
        contract.attachee_id,
        "ðŸ“ Contract Reminder",
        f"Please sign your contract (No: {contract.contract_number}) to complete your registration."
    )
    
    return {"message": "Reminder sent successfully"}


@app.post("/api/contracts/supervisor-reject/{contract_id}")
def supervisor_reject_contract(
    contract_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Supervisor rejects contract and provides notes for revision"""
    
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    
    rejection_reason = data.get('rejection_reason', '')
    supervisor_id = data.get('supervisor_id', 0)
    
    # Update contract status
    contract.status = "rejected"
    contract.rejection_reason = rejection_reason
    contract.supervisor_notes = rejection_reason
    contract.supervisor_id = supervisor_id if supervisor_id else contract.supervisor_id
    contract.updated_at = datetime.now()
    
    # Increment revision count
    if contract.revision_count is None:
        contract.revision_count = 0
    contract.revision_count += 1
    contract.last_revision_at = datetime.now()
    
    # Store revision history
    import json
    revision_entry = {
        "date": datetime.now().isoformat(),
        "action": "rejected",
        "reason": rejection_reason,
        "by": supervisor_id
    }
    
    if contract.revision_history:
        try:
            history = json.loads(contract.revision_history)
            history.append(revision_entry)
            contract.revision_history = json.dumps(history)
        except:
            contract.revision_history = json.dumps([revision_entry])
    else:
        contract.revision_history = json.dumps([revision_entry])
    
    db.commit()
    
    # Notify coordinator
    if contract.created_by:
        background_tasks.add_task(
            send_push_notification,
            contract.created_by,
            "ðŸ“ Contract Needs Changes",
            f"Contract for {contract.full_name} has been returned for changes.\n\nSupervisor notes: {rejection_reason[:150]}"
        )
        
        notification = Notification(
            user_id=contract.created_by,
            title="Contract Requires Changes",
            message=f"Contract for {contract.full_name} was returned by supervisor. Please review the notes and resubmit after making changes.\n\nSupervisor Notes: {rejection_reason}",
            type="contract_rejected"
        )
        db.add(notification)
        db.commit()
    
    # Notify attachee (optional - coordinator will handle)
    background_tasks.add_task(
        send_push_notification,
        contract.attachee_id,
        "ðŸ“ Contract Requires Revision",
        f"Your contract has been returned for changes. Your coordinator will contact you with details."
    )
    
    return {
        "message": "Contract rejected and returned for changes",
        "contract_id": contract_id,
        "revision_count": contract.revision_count,
        "status": "rejected"
    }


@app.get("/api/contracts/all")
def get_all_contracts(db: Session = Depends(get_db_local)):
    """Get all contracts for coordinator view"""
    contracts = db.query(Contract).order_by(Contract.created_at.desc()).all()
    
    result = []
    for contract in contracts:
        attachee = db.query(User).filter(User.id == contract.attachee_id).first()
        result.append({
            "id": contract.id,
            "contract_number": contract.contract_number,
            "student_name": contract.full_name or (attachee.full_name if attachee else "Unknown"),
            "attachee_id": contract.attachee_id,
            "amount_paid": float(contract.amount_paid) if contract.amount_paid else 0,
            "status": contract.status,
            "signed_at": contract.signed_at.isoformat() if contract.signed_at else None,
            "supervisor_approved_at": contract.supervisor_approved_at.isoformat() if contract.supervisor_approved_at else None,
            "department": None  # Will be filled from profile if needed
        })
    
    return result

@app.post("/api/contracts/generate-pdf/{contract_id}")
def generate_contract_pdf(
    contract_id: int,
    db: Session = Depends(get_db_local)
):
    """Generate final PDF contract after approval"""
    
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    
    if contract.status != "approved":
        raise HTTPException(status_code=400, detail="Contract must be approved before generating PDF")
    
    try:
        from contract_pdf import ContractPDFGenerator
        
        generator = ContractPDFGenerator()
        
        contract_data = {
            "contract_number": contract.contract_number,
            "full_name": contract.full_name,
            "id_number": contract.id_number,
            "mobile_phone_1": contract.mobile_phone_1,
            "mobile_phone_2": contract.mobile_phone_2,
            "email": contract.email,
            "school": contract.school,
            "course": contract.course,
            "level": contract.level,
            "start_date": contract.start_date.strftime("%B %d, %Y") if contract.start_date else "_________",
            "end_date": contract.end_date.strftime("%B %d, %Y") if contract.end_date else "_________",
            "school_supervisor": contract.school_supervisor,
            "school_supervisor_phone": contract.school_supervisor_phone,
            "parent_guardian": contract.parent_guardian,
            "parent_guardian_phone": contract.parent_guardian_phone,
            "completion_documents_fee": float(contract.completion_documents_fee) if contract.completion_documents_fee else 1550.00,
            "amount_paid": float(contract.amount_paid) if contract.amount_paid else 0,
            "payment_reference": contract.payment_reference or "Pending",
            "signed_at": contract.signed_at.strftime("%B %d, %Y") if contract.signed_at else datetime.now().strftime("%B %d, %Y"),
            "approved_at": contract.supervisor_approved_at.strftime("%B %d, %Y") if contract.supervisor_approved_at else datetime.now().strftime("%B %d, %Y")
        }
        
        pdf_path = generator.generate_contract(contract_data)
        contract.pdf_path = pdf_path
        db.commit()
        
        return {"message": "PDF generated successfully", "pdf_path": pdf_path}
        
    except Exception as e:
        print(f"Error generating PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Error generating PDF: {str(e)}")


@app.get("/api/contracts/download/{contract_id}")
def download_contract(contract_id: int, db: Session = Depends(get_db_local)):
    """Download contract PDF"""
    
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    
    if not contract.pdf_path or not os.path.exists(contract.pdf_path):
        raise HTTPException(status_code=404, detail="PDF file not found. Please generate PDF first.")
    
    return FileResponse(
        contract.pdf_path,
        media_type='application/pdf',
        filename=f"Contract_{contract.contract_number}.pdf"
    )

@app.post("/api/contracts/remind-supervisor/{contract_id}")
def remind_supervisor(contract_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db_local)):
    """Send reminder to supervisor about pending contract"""
    
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    
    if contract.supervisor_id:
        background_tasks.add_task(
            send_push_notification,
            contract.supervisor_id,
            "ðŸ”” Contract Reminder",
            f"Contract for {contract.full_name} is pending your approval"
        )
    
    return {"message": "Reminder sent to supervisor"}

# ==================== CONTRACT REVISION AND RESUBMISSION ENDPOINTS ====================
# Add these to your main.py file

@app.post("/api/contracts/return-for-changes")
def return_contract_for_changes(
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Coordinator returns contract to student for changes (not rejected - needs revision)"""
    
    contract_id = data.get('contract_id')
    reason = data.get('reason', '')
    
    if not contract_id:
        raise HTTPException(status_code=400, detail="Contract ID required")
    
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    
    # Update contract status to "rejected" but with revision intent
    # Using 'rejected' status but with clear revision notes
    contract.status = "rejected"
    contract.supervisor_notes = reason
    contract.rejection_reason = reason
    contract.updated_at = datetime.now()
    
    db.commit()
    
    # Send notification to attachee
    background_tasks.add_task(
        send_push_notification,
        contract.attachee_id,
        "ðŸ“ Contract Requires Changes",
        f"Your contract needs revision. Coordinator notes: {reason[:100]}... Please review and resubmit."
    )
    
    notification = Notification(
        user_id=contract.attachee_id,
        title="Contract Requires Changes",
        message=f"Please review the notes and make necessary changes to your contract.\n\nNotes: {reason}",
        type="contract_changes"
    )
    db.add(notification)
    
    # Notify coordinator that it was returned
    if contract.created_by:
        coord_notification = Notification(
            user_id=contract.created_by,
            title="Contract Returned for Changes",
            message=f"Contract for {contract.full_name} was returned for changes. Student will resubmit after revision.",
            type="contract_returned"
        )
        db.add(coord_notification)
    
    db.commit()
    
    return {
        "message": f"Contract returned to {contract.full_name} for changes",
        "contract_id": contract_id,
        "status": "rejected"
    }


@app.post("/api/contracts/resubmit-to-supervisor")
def resubmit_contract_to_supervisor(
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Coordinator resubmits a revised contract to supervisor for approval"""
    
    contract_id = data.get('contract_id')
    amount_paid = data.get('amount_paid')
    payment_reference = data.get('payment_reference')
    coordinator_notes = data.get('coordinator_notes', '')
    mode = data.get('mode', 'physical')
    total_fee = data.get('total_fee', 2950 if mode == "physical" else 4950)
    
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    
    # Update contract with payment info and mode
    contract.amount_paid = amount_paid
    contract.payment_reference = payment_reference
    contract.payment_date = datetime.now()
    contract.coordinator_notes = coordinator_notes
    contract.coordinator_approved = True
    contract.coordinator_approved_at = datetime.now()
    contract.status = "pending_supervisor"
    contract.mode = mode
    contract.total_fee = total_fee
    contract.updated_at = datetime.now()
    
    # Clear previous rejection/supervisor notes
    # Keep them for audit but move to a history field? Or just clear
    contract.rejection_reason = None  # Clear rejection reason since resubmitted
    contract.supervisor_notes = None  # Clear old supervisor notes
    
    # Get the supervisor by role
    supervisor = db.query(User).filter(User.role == "supervisor").first()
    
    if supervisor:
        contract.supervisor_id = supervisor.id
        print(f"âœ… Contract {contract.contract_number} resubmitted to supervisor: {supervisor.full_name} (ID: {supervisor.id})")
        
        # Notify supervisor
        background_tasks.add_task(
            send_push_notification,
            supervisor.id,
            "ðŸ“„ Contract Resubmitted for Approval",
            f"Contract for {contract.full_name} ({mode}) has been resubmitted after revisions. Requires your approval."
        )
        
        notification = Notification(
            user_id=supervisor.id,
            title="Contract Resubmitted for Approval",
            message=f"Contract for {contract.full_name} (No: {contract.contract_number}, Mode: {mode}) has been updated and is ready for your review.",
            type="contract"
        )
        db.add(notification)
    else:
        print(f"âš ï¸ No supervisor found in the system!")
        raise HTTPException(status_code=404, detail="No supervisor found to forward the contract")
    
    # Notify attachee that contract was resubmitted
    background_tasks.add_task(
        send_push_notification,
        contract.attachee_id,
        "âœ… Contract Resubmitted",
        f"Your revised contract has been resubmitted to supervisor for approval. You will be notified once approved."
    )
    
    attachee_notification = Notification(
        user_id=contract.attachee_id,
        title="Contract Resubmitted",
        message=f"Your revised contract has been sent to supervisor for approval.",
        type="contract_resubmitted"
    )
    db.add(attachee_notification)
    
    db.commit()
    
    return {
        "message": f"Contract resubmitted to supervisor for approval",
        "supervisor_id": supervisor.id,
        "contract_id": contract.id,
        "mode": mode,
        "total_fee": total_fee,
        "amount_paid": amount_paid
    }


@app.get("/api/contracts/coordinator/{coordinator_id}/revisions")
def get_contracts_needing_revision(
    coordinator_id: int,
    db: Session = Depends(get_db_local)
):
    """Get contracts that were returned for changes (rejected status)"""
    
    # Get contracts created by this coordinator that are in 'rejected' status
    contracts = db.query(Contract).filter(
        Contract.created_by == coordinator_id,
        Contract.status == "rejected"
    ).order_by(Contract.updated_at.desc()).all()
    
    result = []
    for contract in contracts:
        attachee = db.query(User).filter(User.id == contract.attachee_id).first()
        
        result.append({
            "id": contract.id,
            "contract_number": contract.contract_number,
            "full_name": contract.full_name or (attachee.full_name if attachee else "Unknown"),
            "attachee_id": contract.attachee_id,
            "amount_paid": float(contract.amount_paid) if contract.amount_paid else 0,
            "status": contract.status,
            "rejection_reason": contract.rejection_reason,
            "supervisor_notes": contract.supervisor_notes,
            "filled_at": contract.filled_at.isoformat() if contract.filled_at else None,
            "signed_at": contract.signed_at.isoformat() if contract.signed_at else None,
            "created_at": contract.created_at.isoformat() if contract.created_at else None,
            "coordinator_notes": contract.coordinator_notes or "",
            "mode": getattr(contract, 'mode', 'physical'),
            "total_fee": getattr(contract, 'total_fee', 2950)
        })
    
    return result


@app.get("/api/contracts/supervisor/needs-approval/{supervisor_id}")
def get_contracts_needing_approval(
    supervisor_id: int,
    db: Session = Depends(get_db_local)
):
    """Get contracts pending supervisor approval"""
    
    contracts = db.query(Contract).filter(
        Contract.status == "pending_supervisor",
        Contract.supervisor_id == supervisor_id
    ).order_by(Contract.updated_at.desc()).all()
    
    result = []
    for contract in contracts:
        attachee = db.query(User).filter(User.id == contract.attachee_id).first()
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == contract.attachee_id).first()
        
        result.append({
            "id": contract.id,
            "contract_number": contract.contract_number,
            "full_name": contract.full_name or (attachee.full_name if attachee else "Unknown"),
            "attachee_id": contract.attachee_id,
            "student_id": profile.student_id if profile else "N/A",
            "amount_paid": float(contract.amount_paid) if contract.amount_paid else 0,
            "payment_reference": contract.payment_reference,
            "filled_at": contract.filled_at.isoformat() if contract.filled_at else None,
            "signed_at": contract.signed_at.isoformat() if contract.signed_at else None,
            "coordinator_notes": contract.coordinator_notes or "",
            "mode": getattr(contract, 'mode', 'physical'),
            "total_fee": getattr(contract, 'total_fee', 2950),
            "is_resubmission": contract.rejection_reason is not None  # True if this is a resubmission
        })
    
    return result


@app.get("/api/contracts/{contract_id}/revision-history")
def get_contract_revision_history(
    contract_id: int,
    db: Session = Depends(get_db_local)
):
    """Get revision history for a contract"""
    
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    
    # Build revision history
    history = []
    
    # Original creation
    history.append({
        "timestamp": contract.created_at.isoformat() if contract.created_at else None,
        "action": "Contract Created",
        "details": f"Contract {contract.contract_number} created",
        "by": "Coordinator"
    })
    
    # When sent to attachee
    history.append({
        "timestamp": contract.created_at.isoformat() if contract.created_at else None,
        "action": "Contract Sent",
        "details": f"Contract sent to {contract.full_name} for filling",
        "by": "Coordinator"
    })
    
    # When filled by attachee
    if contract.filled_at:
        history.append({
            "timestamp": contract.filled_at.isoformat(),
            "action": "Contract Filled",
            "details": "Student completed and submitted the contract form",
            "by": contract.full_name
        })
    
    # When rejected/returned for changes
    if contract.rejection_reason:
        history.append({
            "timestamp": contract.updated_at.isoformat() if contract.updated_at else None,
            "action": "Contract Returned for Changes",
            "details": f"Supervisor requested changes: {contract.rejection_reason}",
            "by": "Supervisor"
        })
    
    # When resubmitted
    if contract.coordinator_approved_at and contract.rejection_reason:
        history.append({
            "timestamp": contract.coordinator_approved_at.isoformat(),
            "action": "Contract Resubmitted",
            "details": f"Contract resubmitted to supervisor with revisions (Mode: {contract.mode}, Amount: KES {contract.amount_paid:,.2f})",
            "by": "Coordinator"
        })
    
    # When approved
    if contract.supervisor_approved_at:
        history.append({
            "timestamp": contract.supervisor_approved_at.isoformat(),
            "action": "Contract Approved",
            "details": "Contract approved by supervisor",
            "by": "Supervisor"
        })
    
    return {"contract_id": contract_id, "history": history, "current_status": contract.status}

@app.get("/contract.html", response_class=HTMLResponse)
async def serve_contract():
    contract_path = web_dir / "contract.html"
    if contract_path.exists():
        return FileResponse(str(contract_path))
    return HTMLResponse(content="<h1>Contract page not found</h1>", status_code=404)

# ==================== CONTRACT ENDPOINTS (CLEANED UP) ====================

@app.post("/api/contracts/send-form")
def send_contract_form(
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Coordinator or supervisor sends empty contract form to attachee with mode selection"""
    
    attachee_id = data.get('attachee_id')
    sender_id = data.get('sender_id') or data.get('coordinator_id') or data.get('supervisor_id')
    contract_number = data.get('contract_number')
    notes = data.get('notes', '')
    mode = data.get('mode', 'physical')  # Add mode parameter
    total_fee = data.get('total_fee', 2950 if mode == 'physical' else 4950)  # Add total_fee
    
    print(f"ðŸ“ Creating contract for attachee_id: {attachee_id}")
    print(f"   Contract Number: {contract_number}")
    print(f"   Mode: {mode}")
    print(f"   Total Fee: KES {total_fee}")
    
    # Get attachee details
    attachee = db.query(User).filter(User.id == attachee_id, User.role == "attachee").first()
    if not attachee:
        raise HTTPException(status_code=404, detail="Attachee not found")

    sender = db.query(User).filter(User.id == sender_id).first() if sender_id else None
    if not sender or sender.role not in ["coordinator", "supervisor"]:
        raise HTTPException(status_code=403, detail="Only coordinators or supervisors can send contract forms")
    
    # Check if contract already exists for this attachee
    existing_contract = db.query(Contract).filter(
        Contract.attachee_id == attachee_id,
        Contract.status.in_(["sent", "filled", "pending_supervisor"])
    ).first()
    
    if existing_contract:
        print(f"âš ï¸ Contract already exists with status: {existing_contract.status}")
        raise HTTPException(status_code=400, detail="Attachee already has a pending contract")
    
    # Create contract with status 'sent' and include mode
    contract = Contract(
        attachee_id=attachee_id,
        contract_number=contract_number,
        status="sent",
        created_by=sender_id,
        created_at=datetime.now(),
        coordinator_notes=notes,
        mode=mode,  # Store mode
        total_fee=total_fee  # Store total fee
    )
    
    db.add(contract)
    db.commit()
    db.refresh(contract)
    
    print(f"âœ… Contract created with ID: {contract.id}, status: {contract.status}, mode: {mode}")
    
    # Notify attachee
    background_tasks.add_task(
        send_push_notification,
        attachee_id,
        "ðŸ“ Contract Form Ready",
        f"Please fill and submit your {mode} attachment contract form (No: {contract_number})"
    )
    
    notification = Notification(
        user_id=attachee_id,
        title="Contract Form Ready",
        message=f"Please fill and submit your {mode} attachment contract form (No: {contract_number})",
        type="contract"
    )
    db.add(notification)
    db.commit()
    
    return {
        "message": "Contract form sent successfully",
        "contract_id": contract.id,
        "contract_number": contract_number,
        "mode": mode,
        "total_fee": total_fee
    }

@app.post("/api/contracts/submit-filled/{contract_id}")
def submit_filled_contract(
    contract_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Attachee submits filled contract form"""
    
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    
    # Update contract with filled data
    contract.full_name = data.get('full_name')
    contract.id_number = data.get('id_number')
    contract.mobile_phone_1 = data.get('mobile_phone_1')
    contract.mobile_phone_2 = data.get('mobile_phone_2')
    contract.email = data.get('email')
    contract.school = data.get('school')
    contract.course = data.get('course')
    contract.level = data.get('level')
    contract.start_date = datetime.fromisoformat(data.get('start_date')).date() if data.get('start_date') else None
    contract.end_date = datetime.fromisoformat(data.get('end_date')).date() if data.get('end_date') else None
    contract.school_supervisor = data.get('school_supervisor')
    contract.school_supervisor_phone = data.get('school_supervisor_phone')
    contract.parent_guardian = data.get('parent_guardian')
    contract.parent_guardian_phone = data.get('parent_guardian_phone')
    contract.terms_agreed = data.get('terms_agreed', False)
    contract.signed_at = datetime.now()
    contract.signed_by = data.get('full_name')
    contract.status = "filled"
    contract.filled_at = datetime.now()
    contract.filled_by = contract.attachee_id
    
    db.commit()
    
    # Notify coordinator
    coordinators = db.query(User).filter(User.role == "coordinator").all()
    for coord in coordinators:
        background_tasks.add_task(
            send_push_notification,
            coord.id,
            "ðŸ“‹ Contract Filled",
            f"Attachee {contract.full_name} has filled and submitted the contract form"
        )
        
        notification = Notification(
            user_id=coord.id,
            title="Contract Filled",
            message=f"Attachee {contract.full_name} has submitted the contract form for review",
            type="contract"
        )
        db.add(notification)
    
    db.commit()
    
    return {"message": "Contract submitted successfully", "status": "filled"}


@app.post("/api/contracts/forward-to-supervisor")
def forward_contract_to_supervisor(
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Move a filled contract into supervisor approval, whether handled by coordinator or supervisor"""
    
    contract_id = data.get('contract_id')
    amount_paid = data.get('amount_paid')
    payment_reference = data.get('payment_reference')
    coordinator_notes = data.get('coordinator_notes', '')
    actor_id = data.get('actor_id') or data.get('coordinator_id') or data.get('supervisor_id')
    mode = data.get('mode', 'physical')  # Get mode
    total_fee = data.get('total_fee', 2950)  # Get total fee
    
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    actor = db.query(User).filter(User.id == actor_id).first() if actor_id else None
    if not actor or actor.role not in ["coordinator", "supervisor"]:
        raise HTTPException(status_code=403, detail="Only coordinators or supervisors can move contracts to approval")
    
    # Update contract with payment info and mode
    contract.amount_paid = amount_paid
    contract.payment_reference = payment_reference
    contract.payment_date = datetime.now()
    contract.coordinator_notes = coordinator_notes
    contract.coordinator_approved = True
    contract.coordinator_approved_at = datetime.now()
    contract.status = "pending_supervisor"
    contract.mode = mode  # Ensure mode is saved
    contract.total_fee = total_fee  # Ensure total_fee is saved
    
    # Use the acting supervisor directly, otherwise route to the available supervisor.
    supervisor = actor if actor.role == "supervisor" else db.query(User).filter(User.role == "supervisor").first()
    
    if supervisor:
        contract.supervisor_id = supervisor.id
        print(f"âœ… Contract {contract.contract_number} forwarded to supervisor: {supervisor.full_name} (ID: {supervisor.id})")
        
        # Notify supervisor
        background_tasks.add_task(
            send_push_notification,
            supervisor.id,
            "ðŸ“„ Contract Pending Approval",
            f"Contract for {contract.full_name} ({mode}) requires your approval"
        )
        
        notification = Notification(
            user_id=supervisor.id,
            title="Contract Pending Approval",
            message=f"Contract for {contract.full_name} (No: {contract.contract_number}, Mode: {mode}) is ready for your review",
            type="contract"
        )
        db.add(notification)
    else:
        print(f"âš ï¸ No supervisor found in the system!")
        raise HTTPException(status_code=404, detail="No supervisor found to forward the contract")
    
    db.commit()
    
    return {
        "message": "Contract forwarded to supervisor for approval", 
        "supervisor_id": supervisor.id,
        "contract_id": contract.id,
        "mode": mode,
        "total_fee": total_fee,
        "amount_paid": amount_paid
    }


@app.get("/api/contracts/pending-supervisor/{supervisor_id}")
def get_pending_contracts_supervisor(supervisor_id: int, db: Session = Depends(get_db_local)):
    """Get contracts pending supervisor approval"""
    
    print(f"ðŸ” Fetching pending contracts for supervisor ID: {supervisor_id}")
    
    # First, fix any contracts that have null supervisor_id but status pending_supervisor
    # Also fix contracts that might have wrong supervisor_id
    null_contracts = db.query(Contract).filter(
        Contract.status == "pending_supervisor"
    ).all()
    
    for contract in null_contracts:
        if contract.supervisor_id is None or contract.supervisor_id != supervisor_id:
            # Verify this supervisor exists
            supervisor = db.query(User).filter(User.id == supervisor_id, User.role == "supervisor").first()
            if supervisor:
                contract.supervisor_id = supervisor_id
                print(f"ðŸ”§ Fixed contract {contract.contract_number}: assigned supervisor_id={supervisor_id}")
    
    db.commit()
    
    # Now get all pending contracts for this supervisor
    contracts = db.query(Contract).filter(
        Contract.status == "pending_supervisor",
        Contract.supervisor_id == supervisor_id
    ).order_by(Contract.filled_at.desc()).all()
    
    print(f"ðŸ“Š Found {len(contracts)} contracts for supervisor {supervisor_id}")
    
    result = []
    for contract in contracts:
        attachee = db.query(User).filter(User.id == contract.attachee_id).first()
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == contract.attachee_id).first()
        
        result.append({
            "id": contract.id,
            "contract_number": contract.contract_number,
            "full_name": contract.full_name or (attachee.full_name if attachee else "Unknown"),
            "attachee_id": contract.attachee_id,
            "student_id": profile.student_id if profile else "N/A",
            "amount_paid": float(contract.amount_paid) if contract.amount_paid else 0,
            "payment_reference": contract.payment_reference,
            "filled_at": contract.filled_at.isoformat() if contract.filled_at else None,
            "coordinator_notes": contract.coordinator_notes or "",
            "supervisor_notes": contract.supervisor_notes or "",
            "status": contract.status,
            "signed_at": contract.signed_at.isoformat() if contract.signed_at else None,
            "start_date": contract.start_date.isoformat() if contract.start_date else None,
            "end_date": contract.end_date.isoformat() if contract.end_date else None,
            "school": contract.school,
            "course": contract.course,
            "level": contract.level,
            "school_supervisor": contract.school_supervisor,
            "school_supervisor_phone": contract.school_supervisor_phone,
            "parent_guardian": contract.parent_guardian,
            "parent_guardian_phone": contract.parent_guardian_phone,
            "email": contract.email,
            "mobile_phone_1": contract.mobile_phone_1,
            "mobile_phone_2": contract.mobile_phone_2,
            "id_number": contract.id_number,
            "terms_agreed": contract.terms_agreed
        })
    
    return result


# Alternative: Create an endpoint that doesn't require supervisor_id at all
@app.get("/api/contracts/pending-for-supervisor")
def get_pending_contracts_for_supervisor(
    db: Session = Depends(get_db_local)
):
    """Get contracts pending for the supervisor (no ID required)"""
    
    # Get the supervisor by role
    supervisor = db.query(User).filter(User.role == "supervisor").first()
    
    if not supervisor:
        return {"contracts": [], "message": "No supervisor found"}
    
    # Get all pending contracts and assign to this supervisor if not assigned
    pending_contracts = db.query(Contract).filter(
        Contract.status == "pending_supervisor"
    ).all()
    
    for contract in pending_contracts:
        if contract.supervisor_id is None:
            contract.supervisor_id = supervisor.id
            db.commit()
    
    # Now get contracts for this supervisor
    contracts = db.query(Contract).filter(
        Contract.status == "pending_supervisor",
        Contract.supervisor_id == supervisor.id
    ).order_by(Contract.filled_at.desc()).all()
    
    result = []
    for contract in contracts:
        attachee = db.query(User).filter(User.id == contract.attachee_id).first()
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == contract.attachee_id).first()
        
        result.append({
            "id": contract.id,
            "contract_number": contract.contract_number,
            "full_name": contract.full_name or (attachee.full_name if attachee else "Unknown"),
            "attachee_id": contract.attachee_id,
            "student_id": profile.student_id if profile else "N/A",
            "amount_paid": float(contract.amount_paid) if contract.amount_paid else 0,
            "payment_reference": contract.payment_reference,
            "filled_at": contract.filled_at.isoformat() if contract.filled_at else None,
            "coordinator_notes": contract.coordinator_notes or "",
            "status": contract.status
        })
    
    return {"contracts": result, "supervisor": supervisor.full_name}

@app.get("/api/attachee/contracts/pending/{attachee_id}")
def get_pending_attachee_contract(attachee_id: int, db: Session = Depends(get_db_local)):
    """Get pending contract for attachee to fill"""
    
    print(f"ðŸ” Fetching pending contract for attachee_id: {attachee_id}")
    
    # Get the latest contract that is either newly sent or returned for edits
    contract = db.query(Contract).filter(
        Contract.attachee_id == attachee_id,
        Contract.status.in_(["sent", "rejected"])
    ).order_by(Contract.updated_at.desc(), Contract.created_at.desc()).first()
    
    if not contract:
        print(f"âŒ No contract found with status 'sent' for attachee_id: {attachee_id}")
        # Also check if there are any contracts at all for this attachee
        any_contract = db.query(Contract).filter(
            Contract.attachee_id == attachee_id
        ).first()
        if any_contract:
            print(f"âš ï¸ Found contract but status is: {any_contract.status}")
        return {}
    
    print(f"âœ… Found contract: {contract.contract_number}, status: {contract.status}")
    print(f"   Full Name in DB: {contract.full_name}")
    print(f"   ID Number in DB: {contract.id_number}")
    print(f"   Mobile in DB: {contract.mobile_phone_1}")
    
    # Return contract with all fields (some may be empty/None for student to fill)
    return {
        "id": contract.id,
        "contract_number": contract.contract_number,
        "status": contract.status,
        "coordinator_notes": contract.coordinator_notes or "",
        "supervisor_notes": contract.supervisor_notes or "",
        "rejection_reason": contract.rejection_reason or "",
        "revision_count": contract.revision_count or 0,
        "last_revision_at": contract.last_revision_at.isoformat() if contract.last_revision_at else None,
        "full_name": contract.full_name or "",
        "id_number": contract.id_number or "",
        "mobile_phone_1": contract.mobile_phone_1 or "",
        "mobile_phone_2": contract.mobile_phone_2 or "",
        "email": contract.email or "",
        "school": contract.school or "",
        "course": contract.course or "",
        "level": contract.level or "",
        "start_date": contract.start_date.isoformat() if contract.start_date else "",
        "end_date": contract.end_date.isoformat() if contract.end_date else "",
        "school_supervisor": contract.school_supervisor or "",
        "school_supervisor_phone": contract.school_supervisor_phone or "",
        "parent_guardian": contract.parent_guardian or "",
        "parent_guardian_phone": contract.parent_guardian_phone or "",
        "amount_paid": float(contract.amount_paid) if contract.amount_paid else 0,
        "payment_reference": contract.payment_reference or "",
        "terms_agreed": contract.terms_agreed or False,
        "signed_at": contract.signed_at.isoformat() if contract.signed_at else None,
        "created_at": contract.created_at.isoformat() if contract.created_at else None
    }

@app.get("/api/contracts/coordinator/{coordinator_id}")
def get_coordinator_contracts(coordinator_id: int, db: Session = Depends(get_db_local)):
    """Get all contracts for coordinator view - INCLUDING filled data and mode"""
    
    contracts = db.query(Contract).filter(
        Contract.created_by == coordinator_id
    ).order_by(Contract.created_at.desc()).all()
    
    result = []
    for contract in contracts:
        attachee = db.query(User).filter(User.id == contract.attachee_id).first()
        
        result.append({
            "id": contract.id,
            "contract_number": contract.contract_number,
            "full_name": contract.full_name or (attachee.full_name if attachee else "Unknown"),
            "attachee_id": contract.attachee_id,
            "amount_paid": float(contract.amount_paid) if contract.amount_paid else 0,
            "status": contract.status,
            "filled_at": contract.filled_at.isoformat() if contract.filled_at else None,
            "signed_at": contract.signed_at.isoformat() if contract.signed_at else None,
            "created_at": contract.created_at.isoformat() if contract.created_at else None,
            "coordinator_notes": contract.coordinator_notes or "",
            "supervisor_notes": contract.supervisor_notes or "",
            "rejection_reason": contract.rejection_reason or "",
            "mode": getattr(contract, 'mode', 'physical'),  # Add mode field
            "total_fee": getattr(contract, 'total_fee', 2950),  # Add total_fee field
            # Add all the filled fields for display
            "id_number": contract.id_number,
            "mobile_phone_1": contract.mobile_phone_1,
            "mobile_phone_2": contract.mobile_phone_2,
            "email": contract.email,
            "school": contract.school,
            "course": contract.course,
            "level": contract.level,
            "start_date": contract.start_date.isoformat() if contract.start_date else None,
            "end_date": contract.end_date.isoformat() if contract.end_date else None,
            "school_supervisor": contract.school_supervisor,
            "school_supervisor_phone": contract.school_supervisor_phone,
            "parent_guardian": contract.parent_guardian,
            "parent_guardian_phone": contract.parent_guardian_phone,
            "terms_agreed": contract.terms_agreed
        })
    
    return result


app.post("/api/contracts/supervisor-review")
def supervisor_review_contract(
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Supervisor reviews and approves/rejects contract (handles both new and resubmitted)"""
    
    contract_id = data.get('contract_id')
    supervisor_id = data.get('supervisor_id')
    supervisor_notes = data.get('supervisor_notes', '')
    approved = data.get('approved', False)
    
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    
    contract.supervisor_notes = supervisor_notes
    contract.supervisor_id = supervisor_id
    
    if approved:
        contract.supervisor_approved = True
        contract.supervisor_approved_at = datetime.now()
        contract.status = "approved"
        
        # Update attachee profile placement status
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == contract.attachee_id).first()
        if profile:
            profile.placement_status = "placed"
            profile.start_date = contract.start_date if contract.start_date else profile.start_date
            profile.end_date = contract.end_date if contract.end_date else profile.end_date
            if not profile.assigned_supervisor_id:
                profile.assigned_supervisor_id = supervisor_id
            if contract.department:
                profile.department = contract.department
            db.commit()
        
        # Notify attachee
        background_tasks.add_task(
            send_push_notification,
            contract.attachee_id,
            "ðŸŽ‰ Placement Confirmed!",
            f"Congratulations! Your attachment contract has been approved. Welcome to Mfano Bora!"
        )
        
        notification = Notification(
            user_id=contract.attachee_id,
            title="Placement Confirmed!",
            message="Your attachment contract has been approved. The coordinator will generate your final contract.",
            type="placement"
        )
        db.add(notification)
        
        # Notify coordinator
        if contract.created_by:
            if contract.rejection_reason:
                # This was a resubmission
                message = f"Contract for {contract.full_name} has been APPROVED after revision!"
            else:
                message = f"Contract for {contract.full_name} has been approved by supervisor"
            
            background_tasks.add_task(
                send_push_notification,
                contract.created_by,
                "âœ… Contract Approved",
                message
            )
            
            coord_notification = Notification(
                user_id=contract.created_by,
                title="Contract Approved",
                message=message,
                type="contract"
            )
            db.add(coord_notification)
    else:
        # Reject - return for changes
        contract.status = "rejected"
        contract.rejection_reason = supervisor_notes
        
        # Notify coordinator that it needs changes
        if contract.created_by:
            background_tasks.add_task(
                send_push_notification,
                contract.created_by,
                "ðŸ“ Contract Needs Changes",
                f"Supervisor requested changes for {contract.full_name}'s contract. Notes: {supervisor_notes[:100]}..."
            )
        
        # Notify attachee (through coordinator, coordinator will handle)
        background_tasks.add_task(
            send_push_notification,
            contract.attachee_id,
            "ðŸ“ Contract Needs Changes",
            f"Your contract requires changes. Please contact coordinator for details."
        )
    
    db.commit()
    
    return {"message": f"Contract {contract.status} successfully", "status": contract.status}


@app.post("/api/contracts/remind-supervisor/{contract_id}")
def remind_supervisor(contract_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db_local)):
    """Send reminder to supervisor about pending contract"""
    
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    
    # Get the supervisor_id from contract or from attachee's profile
    supervisor_id = contract.supervisor_id
    
    if not supervisor_id:
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == contract.attachee_id).first()
        if profile:
            supervisor_id = profile.assigned_supervisor_id
    
    if supervisor_id:
        background_tasks.add_task(
            send_push_notification,
            supervisor_id,
            "ðŸ”” Contract Reminder",
            f"Contract for {contract.full_name} is pending your approval"
        )
        
        notification = Notification(
            user_id=supervisor_id,
            title="Contract Approval Reminder",
            message=f"Please review contract for {contract.full_name} (No: {contract.contract_number})",
            type="contract_reminder"
        )
        db.add(notification)
        db.commit()
        
        return {"message": "Reminder sent to supervisor"}
    else:
        return {"message": "No supervisor assigned to this contract"}

@app.get("/api/contracts/full/{contract_id}")
def get_full_contract(contract_id: int, db: Session = Depends(get_db_local)):
    """Get full contract details by ID including mode and fee information"""
    
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    
    attachee = db.query(User).filter(User.id == contract.attachee_id).first()
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == contract.attachee_id).first()
    
    return {
        "id": contract.id,
        "contract_number": contract.contract_number,
        "full_name": contract.full_name or (attachee.full_name if attachee else "Unknown"),
        "attachee_id": contract.attachee_id,
        "student_id": profile.student_id if profile else "N/A",
        "id_number": contract.id_number,
        "mobile_phone_1": contract.mobile_phone_1,
        "mobile_phone_2": contract.mobile_phone_2,
        "email": contract.email,
        "school": contract.school,
        "course": contract.course,
        "level": contract.level,
        "start_date": contract.start_date.isoformat() if contract.start_date else None,
        "end_date": contract.end_date.isoformat() if contract.end_date else None,
        "school_supervisor": contract.school_supervisor,
        "school_supervisor_phone": contract.school_supervisor_phone,
        "parent_guardian": contract.parent_guardian,
        "parent_guardian_phone": contract.parent_guardian_phone,
        "amount_paid": float(contract.amount_paid) if contract.amount_paid else 0,
        "payment_reference": contract.payment_reference,
        "coordinator_notes": contract.coordinator_notes or "",
        "supervisor_notes": contract.supervisor_notes or "",
        "status": contract.status,
        "terms_agreed": contract.terms_agreed,
        "signed_at": contract.signed_at.isoformat() if contract.signed_at else None,
        "filled_at": contract.filled_at.isoformat() if contract.filled_at else None,
        "created_at": contract.created_at.isoformat() if contract.created_at else None,
        "mode": getattr(contract, 'mode', 'physical'),  # Add mode field
        "total_fee": getattr(contract, 'total_fee', 2950)  # Add total_fee field
    }

@app.get("/api/contracts/by-attachee/{user_id}")
def get_contract_by_attachee(user_id: int, db: Session = Depends(get_db_local)):
    """Get the latest contract details for an attachee by user ID."""

    contract = db.query(Contract).filter(
        Contract.attachee_id == user_id
    ).order_by(
        Contract.created_at.desc()
    ).first()

    if not contract:
        return {"exists": False, "message": "No contract found"}

    attachee = db.query(User).filter(User.id == contract.attachee_id).first()
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == contract.attachee_id).first()

    return {
        "exists": True,
        "id": contract.id,
        "contract_number": contract.contract_number,
        "full_name": contract.full_name or (attachee.full_name if attachee else "Unknown"),
        "attachee_id": contract.attachee_id,
        "student_id": profile.student_id if profile else "N/A",
        "id_number": contract.id_number,
        "mobile_phone_1": contract.mobile_phone_1,
        "mobile_phone_2": contract.mobile_phone_2,
        "email": contract.email,
        "school": contract.school,
        "course": contract.course,
        "level": contract.level,
        "start_date": contract.start_date.isoformat() if contract.start_date else None,
        "end_date": contract.end_date.isoformat() if contract.end_date else None,
        "school_supervisor": contract.school_supervisor,
        "school_supervisor_phone": contract.school_supervisor_phone,
        "parent_guardian": contract.parent_guardian,
        "parent_guardian_phone": contract.parent_guardian_phone,
        "amount_paid": float(contract.amount_paid) if contract.amount_paid else 0,
        "payment_reference": contract.payment_reference,
        "coordinator_notes": contract.coordinator_notes or "",
        "supervisor_notes": contract.supervisor_notes or "",
        "status": contract.status,
        "terms_agreed": contract.terms_agreed,
        "signed_at": contract.signed_at.isoformat() if contract.signed_at else None,
        "filled_at": contract.filled_at.isoformat() if contract.filled_at else None,
        "created_at": contract.created_at.isoformat() if contract.created_at else None,
        "supervisor_approved_at": contract.supervisor_approved_at.isoformat() if contract.supervisor_approved_at else None,
        "mode": getattr(contract, "mode", "physical"),
        "total_fee": float(contract.total_fee) if getattr(contract, "total_fee", None) else 2950
    }

@app.get("/api/debug/contracts")
def debug_all_contracts(db: Session = Depends(get_db_local)):
    """Debug endpoint to see all contracts"""
    contracts = db.query(Contract).all()
    result = []
    for c in contracts:
        result.append({
            "id": c.id,
            "contract_number": c.contract_number,
            "attachee_id": c.attachee_id,
            "full_name": c.full_name,
            "status": c.status,
            "supervisor_id": c.supervisor_id,
            "filled_at": str(c.filled_at) if c.filled_at else None,
            "created_at": str(c.created_at) if c.created_at else None
        })
    return {"contracts": result, "total": len(result)}
# Add these endpoints to main.py for placements management

@app.post("/api/coordinator/placements/{student_id}/department")
def update_student_department(student_id: int, data: dict, db: Session = Depends(get_db_local)):
    """Update only the department for a student"""
    
    student = db.query(User).filter(User.id == student_id, User.role == "attachee").first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == student_id).first()
    if not profile:
        profile = AttacheeProfile(user_id=student_id)
        db.add(profile)
    
    new_department = data.get('department')
    if new_department:
        profile.department = new_department
    
    db.commit()
    
    return {"message": f"Department updated to {new_department}"}


@app.post("/api/notifications/fee-reminder")
def send_fee_reminder(data: dict, background_tasks: BackgroundTasks, db: Session = Depends(get_db_local)):
    """Send detailed fee reminder to a student based on their actual contract amount"""
    
    user_id = data.get('user_id')
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get the student's profile
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == user_id).first()
    
    # Get the most recent contract for this student (approved or filled)
    contract = db.query(Contract).filter(
        Contract.attachee_id == user_id
    ).order_by(Contract.created_at.desc()).first()
    
    # Get placement information
    department = profile.department if profile else "Not assigned"
    placement_status = profile.placement_status if profile else "not_applied"
    
    # Calculate amounts based on contract
    if contract:
        mode = getattr(contract, 'mode', 'physical')
        mode_display = "ðŸŒ Online" if mode == 'online' else "ðŸ¢ Physical"
        total_fee = float(contract.total_fee) if hasattr(contract, 'total_fee') and contract.total_fee else (4950.00 if mode == 'online' else 2950.00)
        amount_paid = float(contract.amount_paid) if contract.amount_paid else 0.00
        remaining_amount = total_fee - amount_paid
        contract_number = contract.contract_number
        contract_status = contract.status
    else:
        mode_display = "Not determined"
        total_fee = 0.00
        amount_paid = 0.00
        remaining_amount = 0.00
        contract_number = "Not assigned"
        contract_status = "no_contract"
    
    # Format amounts
    total_fee_formatted = f"KES {total_fee:,.2f}" if total_fee > 0 else "Not determined"
    amount_paid_formatted = f"KES {amount_paid:,.2f}" if amount_paid > 0 else "KES 0.00"
    remaining_amount_formatted = f"KES {remaining_amount:,.2f}" if remaining_amount > 0 else "KES 0.00 (Fully Paid)"
    
    # Build detailed message
    if contract_status == "approved" and remaining_amount <= 0:
        message_lines = [
            f"Dear {user.full_name or user.username},",
            f"",
            f"âœ… Your payment is complete!",
            f"",
            f"Contract Details:",
            f"  â€¢ Contract Number: {contract_number}",
            f"  â€¢ Mode: {mode_display}",
            f"  â€¢ Total Fee: {total_fee_formatted}",
            f"  â€¢ Amount Paid: {amount_paid_formatted}",
            f"",
            f"Department: {department}",
            f"Placement Status: {placement_status.upper()}",
            f"",
            f"Thank you for completing your registration."
        ]
        title = "ðŸ’° Payment Complete!"
    elif contract_status == "approved" and remaining_amount > 0:
        message_lines = [
            f"Dear {user.full_name or user.username},",
            f"",
            f"âš ï¸ Payment Reminder",
            f"",
            f"Contract Details:",
            f"  â€¢ Contract Number: {contract_number}",
            f"  â€¢ Mode: {mode_display}",
            f"  â€¢ Total Fee: {total_fee_formatted}",
            f"  â€¢ Amount Paid: {amount_paid_formatted}",
            f"  â€¢ Outstanding Balance: {remaining_amount_formatted}",
            f"",
            f"Department: {department}",
            f"",
            f"Please clear the outstanding balance to complete your placement process.",
            f"You can make the payment via M-PESA Paybill: 552800, Account: 884916"
        ]
        title = "ðŸ’° Fee Payment Reminder"
    else:
        message_lines = [
            f"Dear {user.full_name or user.username},",
            f"",
            f"ðŸ“‹ Contract Required",
            f"",
            f"You have not yet completed your contract form.",
            f"",
            f"Please complete the contract form to proceed with your placement.",
            f"Once completed, you will receive payment instructions.",
            f"",
            f"Department: {department}",
            f"Placement Status: {placement_status.upper()}"
        ]
        title = "ðŸ“‹ Complete Your Contract"
    
    message = "\n".join(message_lines)
    
    # Create notification
    notification = Notification(
        user_id=user_id,
        title=title,
        message=message[:500],  # Limit message length
        type="fee_reminder"
    )
    db.add(notification)
    db.commit()
    
    # Send push notification (shorter version)
    push_message = message_lines[0] + "\n" + message_lines[-1] if len(message_lines) > 1 else message
    background_tasks.add_task(
        send_push_notification,
        user_id,
        title,
        push_message[:200]  # Push notifications have length limits
    )
    
    return {
        "message": "Fee reminder sent successfully",
        "contract_number": contract_number,
        "contract_status": contract_status,
        "mode": mode_display if contract else "not_set",
        "total_fee": total_fee,
        "amount_paid": amount_paid,
        "remaining_amount": remaining_amount,
        "placement_status": placement_status,
        "department": department
    }


@app.get("/api/coordinator/supervisor/by-role")
def get_supervisor_by_role(db: Session = Depends(get_db_local)):
    """Get the single supervisor by role (first supervisor in system)"""
    
    supervisor = db.query(User).filter(User.role == "supervisor").first()
    
    if not supervisor:
        return {"exists": False, "message": "No supervisor found"}
    
    profile = db.query(SupervisorProfile).filter(SupervisorProfile.user_id == supervisor.id).first()
    
    return {
        "exists": True,
        "id": supervisor.id,
        "full_name": supervisor.full_name,
        "email": supervisor.email,
        "phone": supervisor.phone,
        "department": profile.department if profile else None,
        "position": profile.position if profile else None
    }


@app.get("/api/contracts/full/{student_id}")
def get_contract_by_student_id(student_id: int, db: Session = Depends(get_db_local)):
    """Get full contract details for a student"""
    
    # Get the most recent contract for this student
    contract = db.query(Contract).filter(
        Contract.attachee_id == student_id
    ).order_by(Contract.created_at.desc()).first()
    
    if not contract:
        return {
            "exists": False,
            "amount_paid": 0,
            "start_date": None,
            "end_date": None
        }
    
    return {
        "exists": True,
        "id": contract.id,
        "contract_number": contract.contract_number,
        "amount_paid": float(contract.amount_paid) if contract.amount_paid else 0,
        "start_date": contract.start_date.isoformat() if contract.start_date else None,
        "end_date": contract.end_date.isoformat() if contract.end_date else None,
        "status": contract.status,
        "full_name": contract.full_name,
        "school": contract.school,
        "course": contract.course
    }


@app.get("/api/coordinator/password-reset-requests")
def get_password_reset_requests(db: Session = Depends(get_db_local)):
    """Get all pending password reset requests for coordinator"""
    
    requests = db.query(PasswordResetRequest).filter(
        PasswordResetRequest.status == "pending"
    ).order_by(PasswordResetRequest.requested_at.desc()).all()
    
    result = []
    for req in requests:
        result.append({
            "id": req.id,
            "user_id": req.user_id,
            "student_id": req.student_id,
            "student_name": req.student_name,
            "status": req.status,
            "requested_at": req.requested_at.isoformat(),
            "processed_at": req.processed_at.isoformat() if req.processed_at else None
        })

    return result


@app.post("/api/coordinator/password-reset-request/{request_id}/process")
def process_password_reset_request(
    request_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Coordinator approves password reset request"""
    
    reset_request = db.query(PasswordResetRequest).filter(PasswordResetRequest.id == request_id).first()
    if not reset_request:
        raise HTTPException(status_code=404, detail="Request not found")
    
    approved = data.get('approved', True)
    
    if approved:
        # Reset the password
        user = db.query(User).filter(User.id == reset_request.user_id).first()
        if user:
            default_password = "mfanobo123"
            user.set_password(default_password)
            user.password_set = False  # Force password change on next login
            user.updated_at = datetime.now()
            
            reset_request.status = "approved"
            reset_request.processed_at = datetime.now()
            db.commit()
            
            # Send push notification to student
            background_tasks.add_task(
                send_push_notification,
                user.id,
                "ðŸ” Password Reset Approved",
                f"Your password reset request has been approved. New password: {default_password}. Please login and change your password immediately."
            )
            
            notification = Notification(
                user_id=user.id,
                title="Password Reset Approved",
                message=f"Your password has been reset. Please login with password: {default_password} and change it immediately.",
                type="password_reset"
            )
            db.add(notification)
            
            # Notify coordinators
            coordinators = db.query(User).filter(User.role == "coordinator").all()
            for coord in coordinators:
                notification = Notification(
                    user_id=coord.id,
                    title="Password Reset Processed",
                    message=f"Password reset request for {reset_request.student_name} has been approved.",
                    type="password_reset"
                )
                db.add(notification)
            
            db.commit()
            
            return {
                "message": "Password reset approved and processed",
                "student_id": reset_request.student_id,
                "default_password": default_password
            }
    else:
        reset_request.status = "rejected"
        reset_request.processed_at = datetime.now()
        db.commit()
        
        # Notify student
        background_tasks.add_task(
            send_push_notification,
            reset_request.user_id,
            "âŒ Password Reset Denied",
            "Your password reset request has been denied. Please contact the coordinator directly."
        )
        
        return {"message": "Password reset request rejected"}
    
    return {"message": "Request processed"}


@app.delete("/api/coordinator/password-reset-request/{request_id}")
def delete_password_reset_request(
    request_id: int,
    db: Session = Depends(get_db_local)
):
    """Delete a password reset request (when processed)"""
    
    reset_request = db.query(PasswordResetRequest).filter(PasswordResetRequest.id == request_id).first()
    if reset_request:
        db.delete(reset_request)
        db.commit()
    
    return {"message": "Request deleted"}

@app.post("/api/coordinator/reset-password/{student_id}")
def reset_student_password(
    student_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Coordinator resets student password to default"""
    
    student = db.query(User).filter(User.id == student_id, User.role == "attachee").first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    new_password = data.get('new_password', 'mfanobo123')
    
    # Set the new password
    student.set_password(new_password)
    student.password_set = False  # Force password change on next login
    student.updated_at = datetime.now()
    db.commit()
    
    # Send push notification to student
    background_tasks.add_task(
        send_push_notification,
        student_id,
        "ðŸ” Password Reset",
        f"Your password has been reset by the coordinator. Please login with password: {new_password} and change it immediately."
    )
    
    notification = Notification(
        user_id=student_id,
        title="Password Reset",
        message=f"Your password has been reset by the coordinator. Please change your password on next login.",
        type="password_reset"
    )
    db.add(notification)
    db.commit()
    
    return {
        "message": "Password reset successfully",
        "student_id": student_id,
        "student_name": student.full_name,
        "new_password": new_password
    }

# ==================== SUPERVISOR DISABLE REQUESTS ENDPOINTS ====================

@app.get("/api/supervisor/disable-requests/pending")
def get_pending_disable_requests(db: Session = Depends(get_db_local)):
    """Get all pending disable requests for supervisor (from IT Manager)"""
    
    # Get the supervisor (only one in system)
    supervisor = db.query(User).filter(User.role == "supervisor").first()
    if not supervisor:
        return []
    
    # Get all pending disable requests
    requests = db.query(DisableRequest).filter(
        DisableRequest.status == "pending"
    ).order_by(DisableRequest.requested_at.desc()).all()
    
    result = []
    for req in requests:
        # Get target user details
        target_user = db.query(User).filter(User.id == req.target_user_id).first()
        target_profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == req.target_user_id).first() if target_user else None
        
        # Get requester (IT Manager) details
        requester = db.query(User).filter(User.id == req.requested_by).first()
        
        result.append({
            "id": req.id,
            "target_user_id": req.target_user_id,
            "target_name": target_user.full_name if target_user else "Unknown",
            "target_role": req.target_role,
            "target_student_id": target_profile.student_id if target_profile else None,
            "requested_by": req.requested_by,
            "requested_by_name": requester.full_name if requester else "IT Manager",
            "reason": req.reason,
            "status": req.status,
            "requested_at": req.requested_at.isoformat() if req.requested_at else None,
            "rejection_reason": req.rejection_reason
        })
    
    return result


@app.get("/api/supervisor/disable-requests")
def get_all_disable_requests(db: Session = Depends(get_db_local)):
    """Get all disable requests (history) for supervisor"""
    
    requests = db.query(DisableRequest).order_by(DisableRequest.requested_at.desc()).all()
    
    result = []
    for req in requests:
        target_user = db.query(User).filter(User.id == req.target_user_id).first()
        requester = db.query(User).filter(User.id == req.requested_by).first()
        
        result.append({
            "id": req.id,
            "target_name": target_user.full_name if target_user else "Unknown",
            "target_role": req.target_role,
            "requested_by_name": requester.full_name if requester else "IT Manager",
            "reason": req.reason,
            "status": req.status,
            "requested_at": req.requested_at.isoformat() if req.requested_at else None,
            "approved_at": req.approved_at.isoformat() if req.approved_at else None,
            "approved_by": req.approved_by,
            "rejection_reason": req.rejection_reason
        })
    
    return result


@app.post("/api/supervisor/disable-request/{request_id}/process")
def process_disable_request(
    request_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Supervisor approves or rejects a disable request from IT Manager"""
    
    disable_request = db.query(DisableRequest).filter(DisableRequest.id == request_id).first()
    if not disable_request:
        raise HTTPException(status_code=404, detail="Disable request not found")
    
    approved = data.get('approved', False)
    rejection_reason = data.get('rejection_reason', '')
    
    # Get supervisor
    supervisor = db.query(User).filter(User.role == "supervisor").first()
    if not supervisor:
        raise HTTPException(status_code=404, detail="Supervisor not found")
    
    if approved:
        # APPROVE - Disable the user
        target_user = db.query(User).filter(User.id == disable_request.target_user_id).first()
        if target_user:
            # Deactivate user account
            target_user.is_active = False
            target_user.updated_at = datetime.now()
            
            # Update profile status if attachee
            if disable_request.target_role == "attachee":
                profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == target_user.id).first()
                if profile:
                    profile.placement_status = "suspended"
                    profile.updated_at = datetime.now()
            
            # Update disable request status
            disable_request.status = "approved"
            disable_request.approved_at = datetime.now()
            disable_request.approved_by = supervisor.id
            
            db.commit()
            
            # Send notification to target user
            background_tasks.add_task(
                send_push_notification,
                target_user.id,
                "âš ï¸ Account Disabled",
                f"Your account has been disabled by Supervisor. Reason: {disable_request.reason}"
            )
            
            # Send notification to IT Manager who requested
            background_tasks.add_task(
                send_push_notification,
                disable_request.requested_by,
                "âœ… Disable Request Approved",
                f"Your request to disable {target_user.full_name} has been approved by Supervisor."
            )
            
            # Create notifications
            notification = Notification(
                user_id=target_user.id,
                title="Account Disabled",
                message=f"Your account has been disabled. Contact IT Manager for assistance.",
                type="account_disabled"
            )
            db.add(notification)
            
            it_notification = Notification(
                user_id=disable_request.requested_by,
                title="Disable Request Approved",
                message=f"User {target_user.full_name} has been disabled as requested.",
                type="disable_approved"
            )
            db.add(notification)
            db.add(it_notification)
            db.commit()
            
            return {
                "message": f"User {target_user.full_name} has been disabled",
                "status": "approved"
            }
        else:
            raise HTTPException(status_code=404, detail="Target user not found")
    else:
        # REJECT - Keep user active
        disable_request.status = "rejected"
        disable_request.approved_at = datetime.now()
        disable_request.approved_by = supervisor.id
        disable_request.rejection_reason = rejection_reason
        db.commit()
        
        # Get requester and target user info
        requester = db.query(User).filter(User.id == disable_request.requested_by).first()
        target_user = db.query(User).filter(User.id == disable_request.target_user_id).first()
        
        # Send notification to IT Manager
        background_tasks.add_task(
            send_push_notification,
            disable_request.requested_by,
            "âŒ Disable Request Rejected",
            f"Your request to disable {target_user.full_name if target_user else 'user'} has been rejected. Reason: {rejection_reason}"
        )
        
        notification = Notification(
            user_id=disable_request.requested_by,
            title="Disable Request Rejected",
            message=f"Your disable request for {target_user.full_name if target_user else 'user'} was rejected. Reason: {rejection_reason}",
            type="disable_rejected"
        )
        db.add(notification)
        db.commit()
        
        return {
            "message": f"Disable request rejected",
            "status": "rejected"
        }


# ==================== IT MANAGER DISABLE REQUEST ENDPOINTS ====================

@app.post("/api/it-manager/disable-request")
def create_disable_request(
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """IT Manager submits a request to disable a user"""
    
    requested_by = data.get('requested_by')
    target_user_id = data.get('target_user_id')
    reason = data.get('reason', '')
    
    if not requested_by or not target_user_id:
        raise HTTPException(status_code=400, detail="Missing required fields")
    
    # Check if requester is IT Manager
    requester = db.query(User).filter(User.id == requested_by).first()
    if not requester or requester.role != "it_manager":
        raise HTTPException(status_code=403, detail="Only IT Manager can request user disable")
    
    # Get target user
    target_user = db.query(User).filter(User.id == target_user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Target user not found")
    
    # Check if trying to disable the only supervisor
    if target_user.role == "supervisor":
        supervisor_count = db.query(User).filter(User.role == "supervisor", User.is_active == True).count()
        if supervisor_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot disable the only Supervisor in the system")
    
    # Check if there's already a pending request for this user
    existing = db.query(DisableRequest).filter(
        DisableRequest.target_user_id == target_user_id,
        DisableRequest.status == "pending"
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="A pending disable request already exists for this user")
    
    # Create disable request
    disable_request = DisableRequest(
        requested_by=requested_by,
        target_user_id=target_user_id,
        target_role=target_user.role,
        reason=reason,
        status="pending",
        requested_at=datetime.now()
    )
    db.add(disable_request)
    db.commit()
    db.refresh(disable_request)
    
    # Get supervisor
    supervisor = db.query(User).filter(User.role == "supervisor").first()
    
    # Send notification to supervisor
    if supervisor:
        background_tasks.add_task(
            send_push_notification,
            supervisor.id,
            "ðŸ”’ New Disable Request",
            f"IT Manager {requester.full_name} requests to disable {target_user.full_name} ({target_user.role})\nReason: {reason}"
        )
        
        notification = Notification(
            user_id=supervisor.id,
            title="New Disable Request",
            message=f"IT Manager requests to disable {target_user.full_name}. Review and approve/reject.",
            type="disable_request"
        )
        db.add(notification)
    
    # Send confirmation to IT Manager
    background_tasks.add_task(
        send_push_notification,
        requested_by,
        "â³ Disable Request Submitted",
        f"Your request to disable {target_user.full_name} has been sent to Supervisor for approval."
    )
    
    db.commit()
    
    return {
        "message": "Disable request submitted successfully",
        "request_id": disable_request.id,
        "status": "pending"
    }


@app.get("/api/it-manager/disable-requests")
def get_it_manager_disable_requests(
    it_manager_id: int,
    db: Session = Depends(get_db_local)
):
    """Get all disable requests submitted by a specific IT Manager"""
    
    requests = db.query(DisableRequest).filter(
        DisableRequest.requested_by == it_manager_id
    ).order_by(DisableRequest.requested_at.desc()).all()
    
    result = []
    for req in requests:
        target_user = db.query(User).filter(User.id == req.target_user_id).first()
        approver = db.query(User).filter(User.id == req.approved_by).first() if req.approved_by else None
        
        result.append({
            "id": req.id,
            "target_user_id": req.target_user_id,
            "target_name": target_user.full_name if target_user else "Unknown",
            "target_role": req.target_role,
            "reason": req.reason,
            "status": req.status,
            "requested_at": req.requested_at.isoformat() if req.requested_at else None,
            "approved_at": req.approved_at.isoformat() if req.approved_at else None,
            "approved_by": approver.full_name if approver else None,
            "rejection_reason": req.rejection_reason
        })
    
    return result


@app.get("/api/it-manager/disable-requests/pending")
def get_it_manager_pending_requests(
    it_manager_id: int,
    db: Session = Depends(get_db_local)
):
    """Get pending disable requests submitted by a specific IT Manager"""
    
    requests = db.query(DisableRequest).filter(
        DisableRequest.requested_by == it_manager_id,
        DisableRequest.status == "pending"
    ).order_by(DisableRequest.requested_at.desc()).all()
    
    result = []
    for req in requests:
        target_user = db.query(User).filter(User.id == req.target_user_id).first()
        
        result.append({
            "id": req.id,
            "target_name": target_user.full_name if target_user else "Unknown",
            "target_role": req.target_role,
            "reason": req.reason,
            "requested_at": req.requested_at.isoformat() if req.requested_at else None,
            "status": req.status
        })
    
    return result


@app.delete("/api/it-manager/disable-request/{request_id}")
def cancel_disable_request(
    request_id: int,
    it_manager_id: int,
    db: Session = Depends(get_db_local)
):
    """IT Manager cancels a pending disable request"""
    
    disable_request = db.query(DisableRequest).filter(
        DisableRequest.id == request_id,
        DisableRequest.requested_by == it_manager_id,
        DisableRequest.status == "pending"
    ).first()
    
    if not disable_request:
        raise HTTPException(status_code=404, detail="Pending request not found")
    
    disable_request.status = "cancelled"
    db.commit()
    
    # Notify supervisor that request was cancelled
    supervisor = db.query(User).filter(User.role == "supervisor").first()
    if supervisor:
        send_push_notification(
            supervisor.id,
            "ðŸ“‹ Disable Request Cancelled",
            f"IT Manager has cancelled the disable request for user ID {disable_request.target_user_id}"
        )
    
    return {"message": "Disable request cancelled successfully"}


# ==================== DISABLE REQUEST MODEL (Add to models.py) ====================
"""
Add this class to your models.py file:

class DisableRequest(Base):
    __tablename__ = "disable_requests"
    
    id = Column(Integer, primary_key=True, index=True)
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    target_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    target_role = Column(String(50), nullable=False)
    reason = Column(Text, nullable=True)
    status = Column(String(20), default="pending")  # pending, approved, rejected, cancelled
    rejection_reason = Column(Text, nullable=True)
    requested_at = Column(DateTime, default=datetime.now)
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Relationships
    requester = relationship("User", foreign_keys=[requested_by])
    target_user = relationship("User", foreign_keys=[target_user_id])
    approver = relationship("User", foreign_keys=[approved_by])
"""


# ==================== UPDATE MY-STUDENTS ENDPOINT (Add placement_status) ====================

@app.get("/api/supervisor/my-students/{supervisor_id}")
def get_my_students(supervisor_id: int, db: Session = Depends(get_db_local)):
    """Get all attachees assigned to this supervisor (by role, not by ID)"""
    
    # Get all attachees with placement_status = "placed"
    # Since there's only one supervisor, all placed students belong to them
    students = db.query(AttacheeProfile).filter(
        AttacheeProfile.placement_status == "placed"
    ).all()
    
    result = []
    for s in students:
        user = db.query(User).filter(User.id == s.user_id).first()
        if user and user.is_active:
            result.append({
                "id": s.id,
                "user_id": s.user_id,
                "student_id": s.student_id,
                "full_name": user.full_name or user.username,
                "course": s.course,
                "department": s.department,
                "placement_status": s.placement_status,
                "email": user.email,
                "phone": user.phone
            })
    
    return result


# ==================== UPDATE PENDING-LOGBOOKS ENDPOINT ====================

@app.get("/api/supervisor/pending-logbooks/{supervisor_id}")
def get_pending_logbooks(supervisor_id: int, db: Session = Depends(get_db_local)):
    """Get pending logbook entries for supervisor's students"""
    
    # Get the supervisor user by role (since there's only one supervisor)
    supervisor = db.query(User).filter(User.role == "supervisor").first()
    
    if not supervisor:
        print("âš ï¸ No supervisor found in the system")
        return []
    
    print(f"ðŸ” Found supervisor: {supervisor.full_name} (ID: {supervisor.id})")
    print(f"ðŸ” Requested supervisor_id: {supervisor_id}")
    
    # Get all attachees (students) regardless of assigned_supervisor_id
    # Since there's only one supervisor, all students belong to them
    students = db.query(AttacheeProfile).filter(
        AttacheeProfile.placement_status == "placed"
    ).all()
    
    student_ids = [s.user_id for s in students]
    print(f"ðŸ“‹ Found {len(students)} placed students: {student_ids}")
    
    if not student_ids:
        print("âš ï¸ No placed students found")
        return []
    
    # Get pending logbook entries (submitted but no feedback yet)
    pending_entries = db.query(LogbookEntry).filter(
        LogbookEntry.attachee_id.in_(student_ids),
        LogbookEntry.submitted == True,
        LogbookEntry.feedback == None
    ).order_by(LogbookEntry.submitted_at.desc()).all()
    
    print(f"ðŸ““ Found {len(pending_entries)} pending logbook entries")
    
    result = []
    for entry in pending_entries:
        student = db.query(User).filter(User.id == entry.attachee_id).first()
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == entry.attachee_id).first()
        
        result.append({
            "id": entry.id,
            "student_name": student.full_name if student else "Unknown",
            "student_id": profile.student_id if profile else "N/A",
            "title": entry.title,
            "description": entry.description[:200] if entry.description else "",
            "entry_date": entry.entry_date.isoformat(),
            "submitted_at": entry.submitted_at.isoformat() if entry.submitted_at else None,
            "tasks_completed": entry.tasks_completed,
            "challenges": entry.challenges,
            "feedback": entry.feedback
        })
    
    return result

# ==================== IT MANAGER API ENDPOINTS ====================
# Add these to your main.py file

@app.post("/api/it-manager/users")
def create_user_by_it_manager(data: dict, background_tasks: BackgroundTasks, db: Session = Depends(get_db_local)):
    """IT Manager creates a new user - with full placement and all related tables"""
    
    full_name = data.get('full_name')
    username = data.get('username')
    email = data.get('email')
    phone = data.get('phone')
    role = data.get('role')
    password = data.get('password', 'mfanobo123')
    send_notification = data.get('send_notification', True)
    is_fully_placed = data.get('is_fully_placed', False)
    
    if not full_name or not username:
        raise HTTPException(status_code=400, detail="Full name and username are required")
    
    # Check if username exists
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    if email:
        existing_email = db.query(User).filter(User.email == email).first()
        if existing_email:
            raise HTTPException(status_code=400, detail="Email already exists")
    
    # Create user
    new_user = User(
        username=username,
        email=email,
        full_name=full_name,
        role=role,
        is_active=True,
        phone=phone or "",
        password_set=True,
        first_login=False
    )
    new_user.set_password(password)
    db.add(new_user)
    db.flush()
    
    # Create role-specific profile
    if role == "attachee":
        # Get attachee details
        attachee_details = data.get('personal_details', {})
        education_details = data.get('education_details', {})
        contact_details = data.get('contact_details', {})
        contract_details = data.get('contract_details', {})
        placement_details = data.get('placement_details', {})
        
        # Create student ID
        student_id = f"MFB{new_user.id:06d}"
        
        # Create attachee profile
        attachee_profile = AttacheeProfile(
            user_id=new_user.id,
            student_id=student_id,
            course=education_details.get('course', ''),
            institution=education_details.get('institution', ''),
            year_of_study=education_details.get('year_of_study', ''),
            placement_status=placement_details.get('placement_status', 'placed') if is_fully_placed else "not_applied",
            department=placement_details.get('department', 'Not Assigned') if is_fully_placed else None,
            assigned_supervisor_id=placement_details.get('supervisor_id') if is_fully_placed else None,
            start_date=datetime.strptime(placement_details.get('start_date'), "%Y-%m-%d").date() if is_fully_placed and placement_details.get('start_date') else None,
            end_date=datetime.strptime(placement_details.get('end_date'), "%Y-%m-%d").date() if is_fully_placed and placement_details.get('end_date') else None,
            phone_alt=contact_details.get('phone_alt', ''),
            emergency_contact=contact_details.get('emergency_contact', ''),
            address=attachee_details.get('address', ''),
            date_of_birth=datetime.strptime(attachee_details.get('date_of_birth'), "%Y-%m-%d").date() if attachee_details.get('date_of_birth') else None,
            gender=attachee_details.get('gender', ''),
            postal_address=attachee_details.get('postal_address', ''),
            county=attachee_details.get('county', ''),
            education_level=education_details.get('education_level', ''),
            academic_year=education_details.get('academic_year', ''),
            department_applied=placement_details.get('department', '')
        )
        db.add(attachee_profile)
        db.flush()
        
        # Create completed application form
        personal_details_json = json.dumps({
            'full_name': full_name,
            'date_of_birth': attachee_details.get('date_of_birth', ''),
            'id_number': attachee_details.get('id_number', ''),
            'gender': attachee_details.get('gender', ''),
            'physical_address': attachee_details.get('address', ''),
            'postal_address': attachee_details.get('postal_address', ''),
            'mobile': phone,
            'email': email or '',
            'county': attachee_details.get('county', '')
        })
        
        education_json = json.dumps({
            'institution': education_details.get('institution', ''),
            'course': education_details.get('course', ''),
            'education_level': education_details.get('education_level', ''),
            'year_of_study': education_details.get('year_of_study', ''),
            'academic_year': education_details.get('academic_year', '')
        })
        
        skills_json = json.dumps({
            'technical_skills': education_details.get('technical_skills', 'IT Manager placement'),
            'computer_skills': 'Proficient',
            'languages': 'English, Kiswahili',
            'extracurricular': ''
        })
        
        experience_json = json.dumps({
            'previous_experience': 'Pre-placed by IT Manager',
            'motivation': 'Ready for attachment'
        })
        
        app_form = ApplicationForm(
            attachee_id=new_user.id,
            payment_amount=float(contract_details.get('amount_paid', 0)),
            payment_status="paid" if contract_details.get('amount_paid', 0) > 0 else "pending",
            payment_date=datetime.now() if contract_details.get('amount_paid', 0) > 0 else None,
            personal_details=personal_details_json,
            education_background=education_json,
            skills=skills_json,
            experience=experience_json,
            attachment_details=json.dumps({
                'preferred_department': placement_details.get('department', ''),
                'start_date': placement_details.get('start_date', ''),
                'duration': '12 weeks'
            }),
            reference_details=json.dumps({
                'referee_name': contact_details.get('emergency_contact', ''),
                'referee_org': '',
                'referee_position': '',
                'referee_contact': contact_details.get('emergency_phone', '')
            }),
            signature="IT Manager",
            declaration_accepted=True,
            status="completed",
            submitted_at=datetime.now()
        )
        db.add(app_form)
        db.flush()
        
        # Create completed interview
        coordinator = db.query(User).filter(User.role == "coordinator").first()
        interview = Interview(
            attachee_id=new_user.id,
            coordinator_id=coordinator.id if coordinator else new_user.id,
            scheduled_time=datetime.now() - timedelta(days=7),
            duration_minutes=6,
            status="completed",
            interview_time_start=datetime.now() - timedelta(days=7, hours=1),
            interview_time_end=datetime.now() - timedelta(days=7, minutes=55),
            notes="Auto-approved by IT Manager during user creation"
        )
        db.add(interview)
        db.flush()
        
        # Create contract
        contract_number = contract_details.get('contract_number')
        if not contract_number or contract_number == "":
            contract_number = f"CTR-{datetime.now().strftime('%Y%m%d')}-{new_user.id}"
        
        mode = contract_details.get('mode', 'physical')
        total_fee = contract_details.get('total_fee', 4950 if mode == 'online' else 2950)
        amount_paid = float(contract_details.get('amount_paid', 0))
        
        contract = Contract(
            attachee_id=new_user.id,
            contract_number=contract_number,
            amount_paid=amount_paid,
            total_fee=total_fee,
            mode=mode,
            payment_reference=contract_details.get('payment_reference', ''),
            payment_date=datetime.now() if amount_paid > 0 else None,
            terms_agreed=True,
            signed_by=full_name,
            signed_at=datetime.strptime(contract_details.get('signed_date'), "%Y-%m-%d").date() if contract_details.get('signed_date') else datetime.now(),
            coordinator_approved=True,
            coordinator_approved_at=datetime.now(),
            supervisor_approved=True,
            supervisor_approved_at=datetime.now(),
            supervisor_id=placement_details.get('supervisor_id'),
            status="approved",
            full_name=full_name,
            id_number=attachee_details.get('id_number', ''),
            mobile_phone_1=phone,
            mobile_phone_2=contact_details.get('phone_alt', ''),
            email=email or '',
            school=education_details.get('institution', ''),
            course=education_details.get('course', ''),
            level=education_details.get('year_of_study', ''),
            start_date=datetime.strptime(placement_details.get('start_date'), "%Y-%m-%d").date() if placement_details.get('start_date') else None,
            end_date=datetime.strptime(placement_details.get('end_date'), "%Y-%m-%d").date() if placement_details.get('end_date') else None,
            school_supervisor=contact_details.get('parent_guardian', ''),
            school_supervisor_phone=contact_details.get('parent_phone', ''),
            parent_guardian=contact_details.get('emergency_contact', ''),
            parent_guardian_phone=contact_details.get('emergency_phone', '')
        )
        db.add(contract)
        db.flush()
        
        # Update profile with placement status and dates if fully placed
        if is_fully_placed:
            attachee_profile.placement_status = "placed"
            attachee_profile.start_date = contract.start_date
            attachee_profile.end_date = contract.end_date
            attachee_profile.department = placement_details.get('department', '')
            attachee_profile.assigned_supervisor_id = placement_details.get('supervisor_id')
        else:
            attachee_profile.placement_status = "not_applied"
        
        db.commit()
        
        # Send notification if requested
        if send_notification:
            background_tasks.add_task(
                send_push_notification,
                new_user.id,
                "âœ… Account Created",
                f"Your account has been created by IT Manager. Username: {username}, Password: {password}"
            )
            
            notification = Notification(
                user_id=new_user.id,
                title="Account Created",
                message=f"Your account has been created. Please login with your credentials.",
                type="account_created"
            )
            db.add(notification)
            db.commit()
        
        # Log the action
        log_entry = SystemLog(
            user_id=data.get('created_by', new_user.id),
            action="USER_CREATED_FULLY_PLACED" if is_fully_placed else "USER_CREATED",
            details=f"Created user: {full_name} ({username}) with role {role}" + (" and full placement" if is_fully_placed else ""),
            ip_address="127.0.0.1",
            log_type="user_management"
        )
        db.add(log_entry)
        db.commit()
        
        print(f"âœ… Attachee created: ID={new_user.id}, Name={full_name}, Contract={contract_number}, Mode={mode}, Amount=KES {amount_paid}")
        
        return {
            "message": f"User {full_name} created successfully with full placement",
            "user_id": new_user.id,
            "contract_number": contract_number,
            "amount_paid": amount_paid,
            "mode": mode,
            "total_fee": total_fee
        }
    
    elif role == "coordinator":
        profile = CoordinatorProfile(
            user_id=new_user.id,
            department=data.get('department', 'Not Assigned'),
            position=data.get('position', 'Coordinator'),
            office_location=data.get('office_location', '')
        )
        db.add(profile)
        
    elif role == "supervisor":
        profile = SupervisorProfile(
            user_id=new_user.id,
            department=data.get('department', 'Not Assigned'),
            position=data.get('position', 'Supervisor'),
            employee_id=data.get('employee_id', f"SUP{new_user.id:04d}")
        )
        db.add(profile)
        
    elif role == "it_manager":
        profile = SupervisorProfile(
            user_id=new_user.id,
            department="Information Technology",
            position="IT Manager",
            employee_id=data.get('employee_id', f"ITM{new_user.id:04d}")
        )
        db.add(profile)
    
    db.commit()
    
    # Send notification if requested for non-attachee users
    if send_notification and role != "attachee":
        background_tasks.add_task(
            send_push_notification,
            new_user.id,
            "âœ… Account Created",
            f"Your account has been created by IT Manager. Username: {username}, Password: {password}"
        )
        
        notification = Notification(
            user_id=new_user.id,
            title="Account Created",
            message=f"Your account has been created. Please login with your credentials.",
            type="account_created"
        )
        db.add(notification)
        db.commit()
    
    # Log the action
    log_entry = SystemLog(
        user_id=data.get('created_by', new_user.id),
        action="USER_CREATED",
        details=f"Created user: {full_name} ({username}) with role {role}",
        ip_address="127.0.0.1",
        log_type="user_management"
    )
    db.add(log_entry)
    db.commit()
    
    return {"message": f"User {full_name} created successfully", "user_id": new_user.id}

@app.get("/api/it-manager/users")
def get_all_users_for_it_manager(db: Session = Depends(get_db_local)):
    """Get all users for IT Manager (all roles) with placement info"""
    
    users = db.query(User).filter(User.deleted_at == None).all()
    
    result = []
    for user in users:
        profile = None
        placement_status = "N/A"
        
        if user.role == "attachee":
            profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == user.id).first()
            if profile:
                placement_status = profile.placement_status or "not_applied"
                
                # Check if fully placed
                if placement_status == "placed":
                    contract = db.query(Contract).filter(
                        Contract.attachee_id == user.id,
                        Contract.status == "approved"
                    ).first()
                    if contract:
                        placement_status = "Fully Placed"
        
        result.append({
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "email": user.email,
            "phone": user.phone,
            "role": user.role,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "student_id": profile.student_id if profile else None,
            "placement_status": placement_status
        })
    
    return result

@app.get("/api/it-manager/users/{user_id}/is-fully-placed")
def check_user_fully_placed(user_id: int, db: Session = Depends(get_db_local)):
    """Check if a user is fully placed (has all required records)"""
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    result = {
        "user_id": user_id,
        "username": user.username,
        "role": user.role,
        "has_profile": False,
        "has_application": False,
        "has_interview": False,
        "has_contract": False,
        "is_fully_placed": False
    }
    
    if user.role == "attachee":
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == user_id).first()
        result["has_profile"] = profile is not None
        
        application = db.query(ApplicationForm).filter(
            ApplicationForm.attachee_id == user_id,
            ApplicationForm.status == "completed"
        ).first()
        result["has_application"] = application is not None
        
        interview = db.query(Interview).filter(
            Interview.attachee_id == user_id,
            Interview.status == "completed"
        ).first()
        result["has_interview"] = interview is not None
        
        contract = db.query(Contract).filter(
            Contract.attachee_id == user_id,
            Contract.status == "approved"
        ).first()
        result["has_contract"] = contract is not None
        
        result["is_fully_placed"] = all([
            result["has_profile"],
            result["has_application"],
            result["has_interview"],
            result["has_contract"]
        ])
    
    return result


@app.put("/api/it-manager/users/{user_id}")
def update_user_by_it_manager(user_id: int, data: dict, db: Session = Depends(get_db_local)):
    """IT Manager updates a user - including attachee profile, contract, and application data"""
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Update basic user fields
    if 'full_name' in data:
        user.full_name = data['full_name']
    if 'username' in data and data['username'] != user.username:
        existing = db.query(User).filter(User.username == data['username']).first()
        if existing:
            raise HTTPException(status_code=400, detail="Username already exists")
        user.username = data['username']
    if 'email' in data:
        user.email = data['email']
    if 'phone' in data:
        user.phone = data['phone']
    if 'role' in data and data['role'] != user.role:
        user.role = data['role']
    if 'is_active' in data:
        user.is_active = data['is_active']
    
    user.updated_at = datetime.now()
    
    # If user is attachee, update attachee profile, contract, and application
    if user.role == "attachee" and (data.get('personal_details') or data.get('contract_details') or data.get('placement_details')):
        # Get or create profile
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == user_id).first()
        if not profile:
            profile = AttacheeProfile(user_id=user_id, student_id=f"MFB{user_id:06d}")
            db.add(profile)
        
        # Update personal details
        personal = data.get('personal_details', {})
        if personal.get('date_of_birth'):
            try:
                profile.date_of_birth = datetime.strptime(personal['date_of_birth'], "%Y-%m-%d").date()
            except:
                pass
        if personal.get('gender'):
            profile.gender = personal.get('gender')
        if personal.get('id_number'):
            profile.id_number = personal.get('id_number')
        if personal.get('county'):
            profile.county = personal.get('county')
        if personal.get('address'):
            profile.address = personal.get('address')
        if personal.get('postal_address'):
            profile.postal_address = personal.get('postal_address')
        
        # Update education details
        education = data.get('education_details', {})
        if education.get('institution'):
            profile.institution = education.get('institution')
        if education.get('course'):
            profile.course = education.get('course')
        if education.get('year_of_study'):
            profile.year_of_study = education.get('year_of_study')
        if education.get('education_level'):
            profile.education_level = education.get('education_level')
        if education.get('academic_year'):
            profile.academic_year = education.get('academic_year')
        
        # Update contact details
        contact = data.get('contact_details', {})
        if contact.get('phone_alt'):
            profile.phone_alt = contact.get('phone_alt')
        if contact.get('emergency_contact'):
            profile.emergency_contact = contact.get('emergency_contact')
        
        # Update placement details
        placement = data.get('placement_details', {})
        if placement.get('placement_status'):
            profile.placement_status = placement.get('placement_status')
        if placement.get('department'):
            profile.department = placement.get('department')
        if placement.get('start_date'):
            try:
                profile.start_date = datetime.strptime(placement['start_date'], "%Y-%m-%d").date()
            except:
                pass
        if placement.get('end_date'):
            try:
                profile.end_date = datetime.strptime(placement['end_date'], "%Y-%m-%d").date()
            except:
                pass
        
        # Update or create application form
        app_form = db.query(ApplicationForm).filter(
            ApplicationForm.attachee_id == user_id,
            ApplicationForm.status == "completed"
        ).first()
        
        if not app_form:
            app_form = ApplicationForm(
                attachee_id=user_id,
                status="completed",
                submitted_at=datetime.now()
            )
            db.add(app_form)
        
        # Update application form with details
        app_form.personal_details = json.dumps({
            'full_name': user.full_name,
            'date_of_birth': personal.get('date_of_birth', ''),
            'id_number': personal.get('id_number', ''),
            'gender': personal.get('gender', ''),
            'physical_address': personal.get('address', ''),
            'postal_address': personal.get('postal_address', ''),
            'mobile': user.phone,
            'email': user.email or '',
            'county': personal.get('county', '')
        })
        
        app_form.education_background = json.dumps({
            'institution': education.get('institution', ''),
            'course': education.get('course', ''),
            'education_level': education.get('education_level', ''),
            'year_of_study': education.get('year_of_study', ''),
            'academic_year': education.get('academic_year', '')
        })
        
        # Update or create contract
        contract_data = data.get('contract_details', {})
        if contract_data:
            # Check if contract exists
            contract = db.query(Contract).filter(
                Contract.attachee_id == user_id
            ).order_by(Contract.created_at.desc()).first()
            
            if not contract:
                contract_number = contract_data.get('contract_number') or f"CTR-{datetime.now().strftime('%Y%m%d')}-{user_id}"
                contract = Contract(
                    attachee_id=user_id,
                    contract_number=contract_number,
                    created_by=data.get('updated_by', 1),
                    created_at=datetime.now()
                )
                db.add(contract)
            
            # Update contract fields (preserve values that are sent)
            if contract_data.get('mode') is not None:
                contract.mode = contract_data.get('mode')
            if contract_data.get('total_fee') is not None:
                contract.total_fee = contract_data.get('total_fee')
            if contract_data.get('amount_paid') is not None:
                contract.amount_paid = float(contract_data.get('amount_paid'))
            if contract_data.get('payment_reference') is not None:
                contract.payment_reference = contract_data.get('payment_reference')
            if contract_data.get('contract_number') is not None and contract_data.get('contract_number') != "":
                contract.contract_number = contract_data.get('contract_number')
            if contract_data.get('signed_date'):
                try:
                    contract.signed_at = datetime.strptime(contract_data['signed_date'], "%Y-%m-%d")
                except:
                    pass
            
            # Always update these from current user data
            contract.full_name = user.full_name
            contract.email = user.email
            contract.mobile_phone_1 = user.phone
            contract.school = education.get('institution', profile.institution or '')
            contract.course = education.get('course', profile.course or '')
            contract.level = education.get('year_of_study', profile.year_of_study or '')
            contract.id_number = personal.get('id_number', profile.id_number or '')
            contract.parent_guardian = contact.get('parent_guardian', '')
            contract.parent_guardian_phone = contact.get('parent_guardian_phone', '')
            
            # Update dates
            if placement.get('start_date'):
                try:
                    contract.start_date = datetime.strptime(placement['start_date'], "%Y-%m-%d").date()
                except:
                    pass
            if placement.get('end_date'):
                try:
                    contract.end_date = datetime.strptime(placement['end_date'], "%Y-%m-%d").date()
                except:
                    pass
        
        # If placement status is "placed", ensure contract is approved
        if profile.placement_status == "placed":
            contract = db.query(Contract).filter(Contract.attachee_id == user_id).order_by(Contract.created_at.desc()).first()
            if contract and contract.status != "approved":
                contract.status = "approved"
                contract.coordinator_approved = True
                contract.supervisor_approved = True
                contract.supervisor_approved_at = datetime.now()
    
    db.commit()
    
    # Log the action
    log_entry = SystemLog(
        user_id=data.get('updated_by', user_id),
        action="USER_UPDATED",
        details=f"Updated user: {user.full_name} ({user.username})",
        ip_address="127.0.0.1",
        log_type="user_management"
    )
    db.add(log_entry)
    db.commit()
    
    return {"message": f"User {user.full_name} updated successfully"}

@app.post("/api/it-manager/users/{user_id}/reset-password")
def reset_user_password(user_id: int, data: dict, db: Session = Depends(get_db_local)):
    """IT Manager resets a user's password"""
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    new_password = data.get('new_password', 'mfanobo123')
    
    user.set_password(new_password)
    user.password_set = True
    user.updated_at = datetime.now()
    db.commit()
    
    # Log the action
    log_entry = SystemLog(
        user_id=data.get('reset_by', user_id),
        action="PASSWORD_RESET",
        details=f"Reset password for user: {user.full_name} ({user.username})",
        ip_address="127.0.0.1",
        log_type="security"
    )
    db.add(log_entry)
    db.commit()
    
    return {"message": f"Password reset for {user.full_name}", "new_password": new_password}


@app.post("/api/it-manager/users/{user_id}/enable")
def enable_user_by_it_manager(user_id: int, db: Session = Depends(get_db_local)):
    """IT Manager enables a disabled user"""
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.is_active = True
    user.enabled_by = user_id
    user.enabled_at = datetime.now()
    user.updated_at = datetime.now()
    db.commit()
    
    # Log the action
    log_entry = SystemLog(
        user_id=user_id,
        action="USER_ENABLED",
        details=f"Enabled user: {user.full_name} ({user.username})",
        ip_address="127.0.0.1",
        log_type="user_management"
    )
    db.add(log_entry)
    db.commit()
    
    return {"message": f"User {user.full_name} has been enabled"}


# ==================== IT MANAGER - DISABLE REQUESTS ====================

@app.post("/api/it-manager/disable-request")
def create_disable_request(data: dict, background_tasks: BackgroundTasks, db: Session = Depends(get_db_local)):
    """IT Manager submits a request to disable a user"""
    
    requested_by = data.get('requested_by')
    target_user_id = data.get('target_user_id')
    reason = data.get('reason', '')
    
    if not requested_by or not target_user_id:
        raise HTTPException(status_code=400, detail="Missing required fields")
    
    # Check if requester is IT Manager
    requester = db.query(User).filter(User.id == requested_by).first()
    if not requester or requester.role != "it_manager":
        raise HTTPException(status_code=403, detail="Only IT Manager can request user disable")
    
    # Get target user
    target_user = db.query(User).filter(User.id == target_user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Target user not found")
    
    # Check if trying to disable the only supervisor
    if target_user.role == "supervisor":
        supervisor_count = db.query(User).filter(User.role == "supervisor", User.is_active == True).count()
        if supervisor_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot disable the only Supervisor in the system")
    
    # Check if there's already a pending request for this user
    existing = db.query(DisableRequest).filter(
        DisableRequest.target_user_id == target_user_id,
        DisableRequest.status == "pending"
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="A pending disable request already exists for this user")
    
    # Create disable request
    disable_request = DisableRequest(
        requested_by=requested_by,
        target_user_id=target_user_id,
        target_role=target_user.role,
        reason=reason,
        status="pending",
        requested_at=datetime.now()
    )
    db.add(disable_request)
    db.commit()
    db.refresh(disable_request)
    
    # Get supervisor
    supervisor = db.query(User).filter(User.role == "supervisor").first()
    
    # Send notification to supervisor
    if supervisor:
        background_tasks.add_task(
            send_push_notification,
            supervisor.id,
            "ðŸ”’ New Disable Request",
            f"IT Manager {requester.full_name} requests to disable {target_user.full_name} ({target_user.role})\nReason: {reason}"
        )
        
        notification = Notification(
            user_id=supervisor.id,
            title="New Disable Request",
            message=f"IT Manager requests to disable {target_user.full_name}. Review and approve/reject.",
            type="disable_request"
        )
        db.add(notification)
    
    # Log the action
    log_entry = SystemLog(
        user_id=requested_by,
        action="DISABLE_REQUESTED",
        details=f"Requested to disable user: {target_user.full_name} ({target_user.role})",
        ip_address="127.0.0.1",
        log_type="security"
    )
    db.add(log_entry)
    db.commit()
    
    return {
        "message": "Disable request submitted successfully",
        "request_id": disable_request.id,
        "status": "pending"
    }


@app.get("/api/it-manager/disable-requests/{it_manager_id}")
def get_it_manager_disable_requests(it_manager_id: int, db: Session = Depends(get_db_local)):
    """Get all disable requests submitted by a specific IT Manager"""
    
    requests = db.query(DisableRequest).filter(
        DisableRequest.requested_by == it_manager_id
    ).order_by(DisableRequest.requested_at.desc()).all()
    
    result = []
    for req in requests:
        target_user = db.query(User).filter(User.id == req.target_user_id).first()
        approver = db.query(User).filter(User.id == req.approved_by).first() if req.approved_by else None
        
        result.append({
            "id": req.id,
            "target_user_id": req.target_user_id,
            "target_name": target_user.full_name if target_user else "Unknown",
            "target_role": req.target_role,
            "reason": req.reason,
            "status": req.status,
            "requested_at": req.requested_at.isoformat() if req.requested_at else None,
            "approved_at": req.approved_at.isoformat() if req.approved_at else None,
            "approved_by": approver.full_name if approver else None,
            "rejection_reason": req.rejection_reason
        })
    
    return result


# ==================== IT MANAGER - SYSTEM STATS ====================

@app.get("/api/it-manager/system/storage")
def get_storage_usage(db: Session = Depends(get_db_local)):
    """Get detailed storage usage information for all system components"""
    
    storage_info = {
        "uploads": {"used": 0, "used_formatted": "0 B", "percent": 0},
        "database": {"used": 0, "used_formatted": "0 B", "percent": 0},
        "logs": {"used": 0, "used_formatted": "0 B", "percent": 0},
        "backups": {"used": 0, "used_formatted": "0 B", "percent": 0},
        "total": {"used": 0, "total": 100 * 1024 * 1024 * 1024, "total_formatted": "100 GB", "percent": 0}
    }
    
    # Uploads directory
    uploads_dir = Config.get_uploads_path()
    if uploads_dir.exists():
        total_size = sum(f.stat().st_size for f in uploads_dir.rglob('*') if f.is_file())
        storage_info["uploads"]["used"] = total_size
        storage_info["uploads"]["used_formatted"] = format_bytes(total_size)
    
    # Database file
    db_path = Config.get_database_path()
    if db_path.exists():
        db_size = db_path.stat().st_size
        storage_info["database"]["used"] = db_size
        storage_info["database"]["used_formatted"] = format_bytes(db_size)
    
    # Logs directory
    logs_dir = Path("logs")
    if logs_dir.exists():
        log_size = sum(f.stat().st_size for f in logs_dir.rglob('*') if f.is_file())
        storage_info["logs"]["used"] = log_size
        storage_info["logs"]["used_formatted"] = format_bytes(log_size)
    
    # Backups directory
    backups_dir = Config.get_data_dir() / "backups"
    if backups_dir.exists():
        backup_size = sum(f.stat().st_size for f in backups_dir.rglob('*') if f.is_file())
        storage_info["backups"]["used"] = backup_size
        storage_info["backups"]["used_formatted"] = format_bytes(backup_size)
    
    # Calculate total used
    total_used = (storage_info["uploads"]["used"] + 
                  storage_info["database"]["used"] + 
                  storage_info["logs"]["used"] + 
                  storage_info["backups"]["used"])
    
    storage_info["total"]["used"] = total_used
    storage_info["total"]["used_formatted"] = format_bytes(total_used)
    storage_info["total"]["percent"] = (total_used / storage_info["total"]["total"] * 100) if storage_info["total"]["total"] > 0 else 0
    
    # Calculate percentages for individual sections
    total_limit = storage_info["total"]["total"]
    if total_limit > 0:
        storage_info["uploads"]["percent"] = (storage_info["uploads"]["used"] / total_limit * 100)
        storage_info["database"]["percent"] = (storage_info["database"]["used"] / total_limit * 100)
        storage_info["logs"]["percent"] = (storage_info["logs"]["used"] / total_limit * 100)
        storage_info["backups"]["percent"] = (storage_info["backups"]["used"] / total_limit * 100)
    
    return {
        "uploads": {
            "used": storage_info["uploads"]["used"],
            "used_formatted": storage_info["uploads"]["used_formatted"],
            "percent": round(storage_info["uploads"]["percent"], 2)
        },
        "database": {
            "used": storage_info["database"]["used"],
            "used_formatted": storage_info["database"]["used_formatted"],
            "percent": round(storage_info["database"]["percent"], 2)
        },
        "logs": {
            "used": storage_info["logs"]["used"],
            "used_formatted": storage_info["logs"]["used_formatted"],
            "percent": round(storage_info["logs"]["percent"], 2)
        },
        "backups": {
            "used": storage_info["backups"]["used"],
            "used_formatted": storage_info["backups"]["used_formatted"],
            "percent": round(storage_info["backups"]["percent"], 2)
        },
        "total": {
            "used": storage_info["total"]["used"],
            "used_formatted": storage_info["total"]["used_formatted"],
            "total": storage_info["total"]["total"],
            "total_formatted": storage_info["total"]["total_formatted"],
            "percent": round(storage_info["total"]["percent"], 2)
        }
    }


@app.get("/api/it-manager/system/active-ips")
def get_active_ips(db: Session = Depends(get_db_local)):
    """Get active IP addresses connected to the system (optimized)"""
    
    import socket
    from datetime import datetime, timedelta
    
    # Get active WebSocket connections
    try:
        from main import ws_manager
        active_websocket_user_ids = set(ws_manager.active_connections.keys()) if hasattr(ws_manager, 'active_connections') else set()
    except:
        active_websocket_user_ids = set()
    
    # Query recent successful logins (last 24 hours) - LIMIT to 100 most recent
    one_day_ago = datetime.now() - timedelta(hours=24)
    recent_logins = db.query(SystemLog).filter(
        SystemLog.action == "LOGIN_ATTEMPT",
        SystemLog.details.like("%successful%"),
        SystemLog.created_at >= one_day_ago
    ).order_by(SystemLog.created_at.desc()).limit(100).all()
    
    # Use a simple dict for tracking
    ip_data = {}
    current_time = datetime.now()
    
    for log in recent_logins:
        ip = log.ip_address
        if ip and ip != "unknown":
            if ip not in ip_data:
                # Only fetch user data if we need it
                user = None
                if log.user_id:
                    user = db.query(User).filter(User.id == log.user_id).first()
                
                ip_data[ip] = {
                    "ip": ip,
                    "last_seen": log.created_at,
                    "full_name": user.full_name if user else "System",
                    "username": user.username if user else "System",
                    "role": user.role if user else "system",
                    "request_count": 1,
                    "has_websocket": log.user_id in active_websocket_user_ids if log.user_id else False
                }
            else:
                ip_data[ip]["request_count"] += 1
                if log.created_at > ip_data[ip]["last_seen"]:
                    ip_data[ip]["last_seen"] = log.created_at
    
    # Add local server IPs (only if not already present)
    try:
        hostname = socket.gethostname()
        local_ips = socket.gethostbyname_ex(hostname)[2]
        for local_ip in local_ips[:3]:  # Limit to first 3 local IPs
            if local_ip not in ip_data:
                ip_data[local_ip] = {
                    "ip": local_ip,
                    "last_seen": current_time,
                    "full_name": "Local Server",
                    "username": "SERVER",
                    "role": "system",
                    "request_count": 0,
                    "has_websocket": True
                }
    except:
        pass
    
    # Add localhost (if not already present)
    if "127.0.0.1" not in ip_data:
        ip_data["127.0.0.1"] = {
            "ip": "127.0.0.1",
            "last_seen": current_time,
            "full_name": "Local Host",
            "username": "LOCALHOST",
            "role": "system",
            "request_count": 0,
            "has_websocket": False
        }
    
    # Sort by last_seen (most recent first) and limit to 30
    sorted_ips = sorted(ip_data.values(), key=lambda x: x["last_seen"], reverse=True)[:30]
    
    # Format timestamps simply
    def format_time(dt):
        if not dt:
            return "Unknown"
        diff = (current_time - dt).total_seconds()
        if diff < 60:
            return "just now"
        elif diff < 3600:
            mins = int(diff / 60)
            return f"{mins}m ago"
        elif diff < 86400:
            hours = int(diff / 3600)
            return f"{hours}h ago"
        else:
            return dt.strftime("%m/%d %H:%M")
    
    return {
        "active_connections": len(sorted_ips),
        "active_websockets": len(active_websocket_user_ids),
        "ips": [{
            "ip": ip["ip"],
            "full_name": ip["full_name"],
            "username": ip["username"],
            "role": ip["role"],
            "last_seen": format_time(ip["last_seen"]),
            "request_count": ip["request_count"],
            "has_websocket": ip["has_websocket"]
        } for ip in sorted_ips]
    }

@app.get("/api/it-manager/system/performance")
def get_system_performance(db: Session = Depends(get_db_local)):
    """Get detailed system performance metrics (CPU, Memory, Disk)"""
    
    performance = {
        "cpu": {"percent": 0, "cores": 0, "frequency": 0, "load_avg": []},
        "memory": {"percent": 0, "used": 0, "total": 0},
        "disk": {"percent": 0, "used": 0, "total": 0},
        "processes": {"total": 0, "running": 0}
    }
    
    if PSUTIL_AVAILABLE:
        try:
            # CPU info
            performance["cpu"]["percent"] = psutil.cpu_percent(interval=0.5)
            performance["cpu"]["cores"] = psutil.cpu_count()
            freq = psutil.cpu_freq()
            performance["cpu"]["frequency"] = freq.current if freq else 0
            performance["cpu"]["load_avg"] = list(psutil.getloadavg()) if hasattr(psutil, 'getloadavg') else []
            
            # Memory info
            mem = psutil.virtual_memory()
            performance["memory"]["percent"] = mem.percent
            performance["memory"]["used"] = mem.used
            performance["memory"]["total"] = mem.total
            
            # Disk info
            disk = psutil.disk_usage('/')
            performance["disk"]["percent"] = disk.percent
            performance["disk"]["used"] = disk.used
            performance["disk"]["total"] = disk.total
            
            # Process info
            performance["processes"]["total"] = len(psutil.pids())
            running = 0
            for proc in psutil.process_iter(['status']):
                try:
                    if proc.info['status'] == 'running':
                        running += 1
                except:
                    pass
            performance["processes"]["running"] = running
            
        except Exception as e:
            print(f"Error getting performance metrics: {e}")
    else:
        # Fallback values when psutil is not installed
        performance["cpu"]["percent"] = 25
        performance["cpu"]["cores"] = 4
        performance["cpu"]["frequency"] = 0
        performance["memory"]["percent"] = 40
        performance["memory"]["used"] = 4 * 1024 * 1024 * 1024  # 4 GB mock
        performance["memory"]["total"] = 8 * 1024 * 1024 * 1024  # 8 GB mock
        performance["disk"]["percent"] = 50
        performance["disk"]["used"] = 50 * 1024 * 1024 * 1024  # 50 GB mock
        performance["disk"]["total"] = 100 * 1024 * 1024 * 1024  # 100 GB mock
        performance["processes"]["total"] = 50
        performance["processes"]["running"] = 10
    
    return {
        "cpu": {
            "percent": performance["cpu"]["percent"],
            "cores": performance["cpu"]["cores"],
            "frequency": performance["cpu"]["frequency"],
            "load_avg": performance["cpu"]["load_avg"]
        },
        "memory": {
            "percent": performance["memory"]["percent"],
            "used": performance["memory"]["used"],
            "used_formatted": format_bytes(performance["memory"]["used"]),
            "total": performance["memory"]["total"],
            "total_formatted": format_bytes(performance["memory"]["total"])
        },
        "disk": {
            "percent": performance["disk"]["percent"],
            "used": performance["disk"]["used"],
            "used_formatted": format_bytes(performance["disk"]["used"]),
            "total": performance["disk"]["total"],
            "total_formatted": format_bytes(performance["disk"]["total"])
        },
        "processes": {
            "total": performance["processes"]["total"],
            "running": performance["processes"]["running"]
        }
    }


@app.get("/api/it-manager/system/alerts/critical")
def get_critical_alerts(db: Session = Depends(get_db_local)):
    """Get critical system alerts"""
    
    alerts = []
    
    # 1. Check storage usage
    storage_data = get_storage_usage(db)
    storage_percent = storage_data["total"]["percent"]
    
    if storage_percent > 90:
        alerts.append({
            "id": "storage_critical",
            "title": "Storage Critical",
            "message": f"Storage usage is at {storage_percent:.1f}%. Please clean up old files immediately.",
            "severity": "critical",
            "timestamp": datetime.now().isoformat()
        })
    elif storage_percent > 70:
        alerts.append({
            "id": "storage_warning",
            "title": "Storage Warning",
            "message": f"Storage usage is at {storage_percent:.1f}%. Consider cleaning up old files.",
            "severity": "high",
            "timestamp": datetime.now().isoformat()
        })
    
    # 2. Check for failed logins in last hour
    one_hour_ago = datetime.now() - timedelta(hours=1)
    failed_logins = db.query(SystemLog).filter(
        SystemLog.action == "LOGIN_ATTEMPT",
        SystemLog.details.like("%failed%"),
        SystemLog.created_at >= one_hour_ago
    ).count()
    
    if failed_logins > 10:
        alerts.append({
            "id": "failed_logins",
            "title": "Multiple Failed Logins",
            "message": f"{failed_logins} failed login attempts in the last hour. Possible brute force attack.",
            "severity": "high",
            "timestamp": datetime.now().isoformat()
        })
    elif failed_logins > 5:
        alerts.append({
            "id": "failed_logins_warning",
            "title": "Increased Failed Logins",
            "message": f"{failed_logins} failed login attempts in the last hour.",
            "severity": "medium",
            "timestamp": datetime.now().isoformat()
        })
    
    # 3. Check for pending disable requests older than 2 days
    two_days_ago = datetime.now() - timedelta(days=2)
    pending_disables = db.query(DisableRequest).filter(
        DisableRequest.status == "pending",
        DisableRequest.requested_at <= two_days_ago
    ).count()
    
    if pending_disables > 0:
        alerts.append({
            "id": "pending_disables",
            "title": "Pending Disable Requests",
            "message": f"{pending_disables} disable request(s) pending for more than 2 days.",
            "severity": "medium",
            "timestamp": datetime.now().isoformat()
        })
    
    # 4. Check system performance if psutil is available
    if PSUTIL_AVAILABLE:
        try:
            cpu_percent = psutil.cpu_percent(interval=0.5)
            if cpu_percent > 90:
                alerts.append({
                    "id": "high_cpu",
                    "title": "High CPU Usage",
                    "message": f"CPU usage is at {cpu_percent:.1f}%. System may be under heavy load.",
                    "severity": "high",
                    "timestamp": datetime.now().isoformat()
                })
            elif cpu_percent > 70:
                alerts.append({
                    "id": "high_cpu_warning",
                    "title": "Elevated CPU Usage",
                    "message": f"CPU usage is at {cpu_percent:.1f}%.",
                    "severity": "medium",
                    "timestamp": datetime.now().isoformat()
                })
            
            memory_percent = psutil.virtual_memory().percent
            if memory_percent > 90:
                alerts.append({
                    "id": "high_memory",
                    "title": "High Memory Usage",
                    "message": f"Memory usage is at {memory_percent:.1f}%.",
                    "severity": "high",
                    "timestamp": datetime.now().isoformat()
                })
        except:
            pass
    
    return {"alerts": alerts}


@app.post("/api/it-manager/system/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: str, db: Session = Depends(get_db_local)):
    """Mark an alert as resolved (logs to system logs)"""
    
    # Log the resolution
    log_entry = SystemLog(
        user_id=None,
        action="ALERT_RESOLVED",
        details=f"Alert '{alert_id}' was resolved",
        ip_address="system",
        log_type="system"
    )
    db.add(log_entry)
    db.commit()
    
    return {"message": "Alert resolved"}


def format_bytes(bytes_value):
    """Format bytes to human readable format"""
    if bytes_value == 0:
        return "0 B"
    k = 1024
    sizes = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while bytes_value >= k and i < len(sizes) - 1:
        bytes_value /= k
        i += 1
    return f"{bytes_value:.2f} {sizes[i]}"

# ==================== IT MANAGER - SYSTEM LOGS ====================

@app.get("/api/it-manager/system-logs")
def get_system_logs(
    limit: int = 100,
    log_type: str = None,
    db: Session = Depends(get_db_local)
):
    """Get system logs for IT Manager"""
    
    query = db.query(SystemLog).order_by(SystemLog.created_at.desc())
    
    if log_type and log_type != "All":
        query = query.filter(SystemLog.log_type == log_type.lower())
    
    logs = query.limit(limit).all()
    
    result = []
    for log in logs:
        user = db.query(User).filter(User.id == log.user_id).first()
        result.append({
            "id": log.id,
            "timestamp": log.created_at.isoformat() if log.created_at else None,
            "user": user.full_name if user else "System",
            "role": user.role if user else "system",
            "action": log.action,
            "details": log.details,
            "ip": log.ip_address,
            "type": log.log_type
        })
    
    return result


# ==================== IT MANAGER - SYSTEM SETTINGS ====================

@app.get("/api/it-manager/settings")
def get_system_settings(db: Session = Depends(get_db_local)):
    """Get all system settings"""
    
    settings = db.query(SystemSetting).all()
    
    result = {}
    for setting in settings:
        value = setting.setting_value
        if setting.setting_type == "boolean":
            value = value.lower() == "true"
        elif setting.setting_type == "integer":
            try:
                value = int(value)
            except:
                pass
        result[setting.setting_key] = value
    
    # Default values if not in database
    defaults = {
        "system_name": "Mfano Bora Attachment System",
        "company_name": "Mfano Bora Africa Ltd",
        "session_timeout": 30,
        "auto_refresh": True,
        "min_password_length": 6,
        "require_uppercase": True,
        "require_lowercase": True,
        "require_numbers": True,
        "require_special": False,
        "max_login_attempts": 5,
        "lockout_duration": 15,
        "push_notifications": True,
        "email_notifications": True,
        "daily_summary": False
    }
    
    for key, default in defaults.items():
        if key not in result:
            result[key] = default
    
    return result


@app.post("/api/it-manager/settings")
def update_system_settings(data: dict, db: Session = Depends(get_db_local)):
    """Update system settings"""
    
    for key, value in data.items():
        setting = db.query(SystemSetting).filter(SystemSetting.setting_key == key).first()
        
        if setting:
            setting.setting_value = str(value)
            setting.updated_at = datetime.now()
        else:
            # Determine type
            setting_type = "string"
            if isinstance(value, bool):
                setting_type = "boolean"
            elif isinstance(value, int):
                setting_type = "integer"
            
            setting = SystemSetting(
                setting_key=key,
                setting_value=str(value),
                setting_type=setting_type,
                description=f"System setting for {key}"
            )
            db.add(setting)
    
    db.commit()
    
    return {"message": "Settings saved successfully"}


# ==================== IT MANAGER - BACKUP ====================

@app.get("/api/it-manager/backups")
def get_backup_list(db: Session = Depends(get_db_local)):
    """Get list of database backups"""
    
    backups = db.query(BackupHistory).order_by(BackupHistory.created_at.desc()).all()
    
    result = []
    for backup in backups:
        result.append({
            "id": backup.id,
            "name": backup.backup_name,
            "created_at": backup.created_at.isoformat() if backup.created_at else None,
            "size_kb": round(backup.backup_size_bytes / 1024, 2) if backup.backup_size_bytes else 0,
            "status": backup.status,
            "type": backup.backup_type
        })
    
    return result


@app.post("/api/it-manager/backups/create")
def create_database_backup(background_tasks: BackgroundTasks, db: Session = Depends(get_db_local)):
    """Create a database backup"""
    
    import shutil
    import subprocess
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"backup_{timestamp}.db"
    
    backup_dir = Config.get_data_dir() / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / backup_name
    
    db_path = Config.get_database_path()
    
    try:
        # Copy database file
        shutil.copy2(db_path, backup_path)
        backup_size = backup_path.stat().st_size
        
        # Record backup in database
        backup_record = BackupHistory(
            backup_name=backup_name,
            backup_path=str(backup_path),
            backup_size_bytes=backup_size,
            backup_type="manual",
            status="completed",
            created_at=datetime.now()
        )
        db.add(backup_record)
        db.commit()
        
        return {"message": "Backup created successfully", "backup_name": backup_name}
        
    except Exception as e:
        print(f"Backup error: {e}")
        raise HTTPException(status_code=500, detail=f"Backup failed: {str(e)}")


@app.delete("/api/it-manager/backups/{backup_id}")
def delete_backup(backup_id: int, db: Session = Depends(get_db_local)):
    """Delete a backup"""
    
    backup = db.query(BackupHistory).filter(BackupHistory.id == backup_id).first()
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")
    
    # Delete file if exists
    import os
    if backup.backup_path and os.path.exists(backup.backup_path):
        os.remove(backup.backup_path)
    
    db.delete(backup)
    db.commit()
    
    return {"message": "Backup deleted successfully"}


# ==================== IT MANAGER - FACE RECOGNITION ISSUES ====================

@app.get("/api/it-manager/face-recognition-issues")
def get_face_recognition_issues(db: Session = Depends(get_db_local)):
    """Get users with face recognition issues"""
    
    # Get attachees with face recognition issues
    users_with_issues = db.query(AttacheeProfile).filter(
        AttacheeProfile.face_recognition_issues > 0
    ).all()
    
    result = []
    for profile in users_with_issues:
        user = db.query(User).filter(User.id == profile.user_id).first()
        result.append({
            "id": user.id,
            "user_id": user.id,
            "full_name": user.full_name,
            "student_id": profile.student_id,
            "failed_attempts": profile.face_recognition_issues,
            "last_failure": profile.last_face_failure.isoformat() if profile.last_face_failure else None,
            "face_status": "registered" if profile.face_encoding else "not_registered"
        })
    
    return result


@app.get("/api/it-manager/face-recognition-issues/count")
def get_face_recognition_issues_count(db: Session = Depends(get_db_local)):
    """Get count of users with face recognition issues"""
    
    count = db.query(AttacheeProfile).filter(
        AttacheeProfile.face_recognition_issues > 0
    ).count()
    
    return {"count": count}


@app.post("/api/it-manager/recalibrate-face")
def recalibrate_face(data: dict, db: Session = Depends(get_db_local)):
    """Recalibrate face recognition for a user"""
    
    user_id = data.get('user_id')
    reason = data.get('reason', '')
    
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == user_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="User profile not found")
    
    # Reset face data
    profile.face_encoding = None
    profile.face_registered_at = None
    profile.face_recognition_issues = 0
    profile.face_last_verified_at = None
    profile.face_issue_reason = reason
    
    db.commit()
    
    return {"message": "Face data recalibrated successfully"}

# Add this middleware to main.py to log all requests
@app.middleware("http")
async def log_all_requests(request: FastAPIRequest, call_next):
    start_time = datetime.now()
    
    # Log the request
    client_ip = request.client.host if request.client else "unknown"
    method = request.method
    path = request.url.path
    
    response = await call_next(request)
    
    process_time = (datetime.now() - start_time).total_seconds()
    
    # Log to database
    try:
        db = next(get_db_local())
        log_entry = SystemLog(
            user_id=None,  # Will be set if authenticated
            action=f"{method} {path}",
            details=f"Status: {response.status_code}, Time: {process_time:.3f}s",
            ip_address=client_ip,
            log_type="api"
        )
        db.add(log_entry)
        db.commit()
        db.close()
    except:
        pass
    
    return response

# ==================== IT MANAGER DASHBOARD API ENDPOINTS ====================

@app.get("/api/it-manager/statistics/users")
def get_user_statistics(db: Session = Depends(get_db_local)):
    """Get user statistics for IT Manager dashboard"""
    
    total_users = db.query(User).filter(User.deleted_at == None).count()
    active_users = db.query(User).filter(User.is_active == True, User.deleted_at == None).count()
    
    pending_disable_requests = db.query(DisableRequest).filter(
        DisableRequest.status == "pending"
    ).count()
    
    # Calculate system uptime (you can track this in a system_settings table)
    # For now, return a mock value
    system_uptime = 86400 * 45  # 45 days in seconds
    
    return {
        "totalUsers": total_users,
        "activeUsers": active_users,
        "pendingDisableRequests": pending_disable_requests,
        "systemUptime": system_uptime
    }


@app.get("/api/it-manager/system/storage")
def get_system_storage(db: Session = Depends(get_db_local)):
    """Get detailed storage usage"""
    
    uploads_dir = Config.get_uploads_path()
    total_storage = 100 * 1024 * 1024 * 1024  # 100 GB limit
    
    # Uploads
    uploads_used = 0
    if uploads_dir.exists():
        uploads_used = sum(f.stat().st_size for f in uploads_dir.rglob('*') if f.is_file())
    
    # Database
    db_path = Config.get_database_path()
    db_used = db_path.stat().st_size if db_path.exists() else 0
    
    # Logs
    logs_dir = Path("logs")
    logs_used = sum(f.stat().st_size for f in logs_dir.rglob('*') if f.is_file()) if logs_dir.exists() else 0
    
    # Backups
    backups_dir = Config.get_data_dir() / "backups"
    backups_used = sum(f.stat().st_size for f in backups_dir.rglob('*') if f.is_file()) if backups_dir.exists() else 0
    
    total_used = uploads_used + db_used + logs_used + backups_used
    total_percent = (total_used / total_storage * 100) if total_storage > 0 else 0
    
    def format_bytes(b):
        if b == 0: return "0 B"
        k = 1024
        sizes = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        while b >= k and i < len(sizes) - 1:
            b /= k
            i += 1
        return f"{b:.2f} {sizes[i]}"
    
    return {
        "uploads": {
            "used": uploads_used,
            "used_formatted": format_bytes(uploads_used),
            "percent": (uploads_used / total_storage * 100) if total_storage > 0 else 0
        },
        "database": {
            "used": db_used,
            "used_formatted": format_bytes(db_used),
            "percent": (db_used / total_storage * 100) if total_storage > 0 else 0
        },
        "logs": {
            "used": logs_used,
            "used_formatted": format_bytes(logs_used),
            "percent": (logs_used / total_storage * 100) if total_storage > 0 else 0
        },
        "backups": {
            "used": backups_used,
            "used_formatted": format_bytes(backups_used),
            "percent": (backups_used / total_storage * 100) if total_storage > 0 else 0
        },
        "total": {
            "used": total_used,
            "used_formatted": format_bytes(total_used),
            "total": total_storage,
            "total_formatted": format_bytes(total_storage),
            "percent": total_percent
        }
    }


@app.get("/api/it-manager/system/performance")
def get_system_performance(db: Session = Depends(get_db_local)):
    """Get system performance metrics"""
    
    # Try to get real metrics, fallback to mock
    try:
        import psutil
        cpu_percent = psutil.cpu_percent(interval=0.5)
        memory_percent = psutil.virtual_memory().percent
        cpu_cores = psutil.cpu_count()
        cpu_freq = psutil.cpu_freq().current if psutil.cpu_freq() else 0
        disk = psutil.disk_usage('/')
        processes = len(psutil.pids())
    except ImportError:
        # Mock values if psutil not installed
        cpu_percent = 25
        memory_percent = 40
        cpu_cores = 4
        cpu_freq = 0
        disk = type('obj', (object,), {'percent': 50, 'used': 50*1024*1024*1024, 'total': 100*1024*1024*1024})()
        processes = 50
    
    def format_bytes(b):
        if b == 0: return "0 B"
        k = 1024
        sizes = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        while b >= k and i < len(sizes) - 1:
            b /= k
            i += 1
        return f"{b:.2f} {sizes[i]}"
    
    return {
        "cpu": {
            "percent": cpu_percent,
            "cores": cpu_cores,
            "frequency": cpu_freq
        },
        "memory": {
            "percent": memory_percent,
            "used": 0,  # Would need to calculate
            "used_formatted": "N/A",
            "total": 0,
            "total_formatted": "N/A"
        },
        "disk": {
            "percent": disk.percent,
            "used": disk.used,
            "used_formatted": format_bytes(disk.used),
            "total": disk.total,
            "total_formatted": format_bytes(disk.total)
        },
        "processes": {
            "total": processes,
            "running": processes // 2
        }
    }



@app.get("/api/it-manager/system-health")
def get_system_health_check(db: Session = Depends(get_db_local)):
    """Simple system health check for status indicators"""
    
    # Check server
    server_online = True
    
    # Check database
    try:
        db.execute("SELECT 1")
        db_connected = True
    except:
        db_connected = False
    
    return {
        "server_online": server_online,
        "db_connected": db_connected
    }


@app.get("/api/it-manager/recent-activity")
def get_recent_activity_list(limit: int = 20, db: Session = Depends(get_db_local)):
    """Get recent system activity for IT Manager dashboard"""
    
    recent_logs = db.query(SystemLog).order_by(SystemLog.created_at.desc()).limit(limit).all()
    
    activities = []
    for log in recent_logs:
        user = db.query(User).filter(User.id == log.user_id).first()
        
        # Determine activity type
        activity_type = "system"
        if "login" in log.action.lower():
            activity_type = "login"
        elif "create" in log.action.lower():
            activity_type = "user_create"
        elif "update" in log.action.lower():
            activity_type = "user_update"
        elif "delete" in log.action.lower():
            activity_type = "user_delete"
        elif "backup" in log.action.lower():
            activity_type = "backup"
        elif "attendance" in log.action.lower():
            activity_type = "attendance"
        
        def format_datetime(dt):
            if not dt: return "Unknown"
            diff = datetime.now() - dt
            if diff.total_seconds() < 60:
                return "just now"
            elif diff.total_seconds() < 3600:
                mins = int(diff.total_seconds() / 60)
                return f"{mins} minute{'s' if mins != 1 else ''} ago"
            elif diff.total_seconds() < 86400:
                hours = int(diff.total_seconds() / 3600)
                return f"{hours} hour{'s' if hours != 1 else ''} ago"
            else:
                return dt.strftime("%Y-%m-%d %H:%M")
        
        activities.append({
            "user": user.full_name if user else "System",
            "description": log.details[:100] if log.details else log.action,
            "timestamp": log.created_at,
            "type": activity_type,
            "ip": log.ip_address
        })
    
    return activities


@app.get("/api/it-manager/system/alerts/critical")
def get_critical_alerts_list(db: Session = Depends(get_db_local)):
    """Get critical system alerts"""
    
    from datetime import datetime, timedelta
    
    alerts = []
    
    # Check storage
    storage_data = get_system_storage(db)
    storage_percent = storage_data["total"]["percent"]
    
    if storage_percent > 90:
        alerts.append({
            "id": "storage_critical",
            "title": "Storage Critical",
            "message": f"Storage usage is at {storage_percent:.1f}%. Please clean up old files.",
            "severity": "critical",
            "timestamp": datetime.now().isoformat()
        })
    elif storage_percent > 70:
        alerts.append({
            "id": "storage_warning",
            "title": "Storage Warning",
            "message": f"Storage usage is at {storage_percent:.1f}%. Consider cleaning up.",
            "severity": "high",
            "timestamp": datetime.now().isoformat()
        })
    
    # Check failed logins
    one_hour_ago = datetime.now() - timedelta(hours=1)
    failed_logins = db.query(SystemLog).filter(
        SystemLog.action == "LOGIN_ATTEMPT",
        SystemLog.details.like("%failed%"),
        SystemLog.created_at >= one_hour_ago
    ).count()
    
    if failed_logins > 10:
        alerts.append({
            "id": "failed_logins",
            "title": "Multiple Failed Logins",
            "message": f"{failed_logins} failed login attempts in the last hour. Possible brute force attack.",
            "severity": "high",
            "timestamp": datetime.now().isoformat()
        })
    
    return {"alerts": alerts}


@app.post("/api/it-manager/system/alerts/{alert_id}/resolve")
def resolve_alert_endpoint(alert_id: str, db: Session = Depends(get_db_local)):
    """Mark an alert as resolved"""
    # Log the resolution
    log_entry = SystemLog(
        user_id=None,
        action="ALERT_RESOLVED",
        details=f"Alert '{alert_id}' was resolved",
        ip_address="system",
        log_type="system"
    )
    db.add(log_entry)
    db.commit()
    
    return {"message": "Alert resolved"}

# ==================== AUTHENTICATION DEPENDENCIES ====================

def get_current_user(request: FastAPIRequest, db: Session = Depends(get_db_local)):
    """Get current user from session or token."""
    # Method 1: Check for user_id in headers (for desktop app)
    user_id = request.headers.get("X-User-Id")
    
    if user_id:
        try:
            user = db.query(User).filter(User.id == int(user_id), User.is_active == True).first()
            if user:
                return user
        except:
            pass
    
    # Method 2: Check for session token in cookies (for web interface)
    token = request.cookies.get("session_token")
    if token:
        # Implement your session token validation here
        # For now, return a default or raise exception
        pass
    
    # Method 3: For development - return a default user (REMOVE IN PRODUCTION!)
    # This is only for testing when authentication isn't fully set up
    default_user = db.query(User).filter(User.role == "it_manager", User.is_active == True).first()
    if default_user:
        print("âš ï¸ Using default user for authentication (development mode)")
        return default_user
    
    raise HTTPException(status_code=401, detail="Not authenticated")

# ==================== IT MANAGER - ATTENDANCE ERRORS ENDPOINTS ====================

@app.get("/api/it-manager/attendance-errors")
async def get_attendance_errors(
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    error_type: str = Query("All", description="Error type filter"),
    db: Session = Depends(get_db_local)
):
    """Get attendance errors/issues for IT Manager dashboard."""
    
    # Parse dates
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    errors = []
    
    # Query all attendance records within date range
    attendance_records = db.query(Attendance).filter(
        Attendance.date >= start,
        Attendance.date <= end
    ).all()
    
    # Query face recognition issues from attachee_profiles
    face_issue_attachees = db.query(AttacheeProfile).filter(
        AttacheeProfile.face_recognition_issues > 0
    ).all()
    face_issue_user_ids = [p.user_id for p in face_issue_attachees]
    
    # Process errors
    for record in attendance_records:
        attachee = db.query(User).filter(User.id == record.attachee_id).first()
        if not attachee:
            continue
        
        # Face Recognition Issues
        if error_type in ["All", "Face Recognition"]:
            if record.attachee_id in face_issue_user_ids:
                face_profile = next((p for p in face_issue_attachees if p.user_id == record.attachee_id), None)
                errors.append({
                    "id": f"face_{record.id}_{record.date.isoformat()}",
                    "date": record.date.isoformat(),
                    "student_id": attachee.username,
                    "student_name": attachee.full_name,
                    "error_type": "Face Recognition",
                    "description": f"Student has {face_profile.face_recognition_issues if face_profile else 0} face recognition issue(s).",
                    "status": "pending",
                    "resolved": False
                })
        
        # Late Check-in
        if error_type in ["All", "Late Check-in"]:
            if record.check_in_time:
                check_in_str = str(record.check_in_time)
                if ':' in check_in_str:
                    parts = check_in_str.split(':')
                    check_in_hour = int(parts[0])
                    check_in_minute = int(parts[1]) if len(parts) > 1 else 0
                    if check_in_hour > 9 or (check_in_hour == 9 and check_in_minute > 0):
                        errors.append({
                            "id": f"late_{record.id}_{record.date.isoformat()}",
                            "date": record.date.isoformat(),
                            "student_id": attachee.username,
                            "student_name": attachee.full_name,
                            "error_type": "Late Check-in",
                            "description": f"Checked in at {record.check_in_time} (expected by 7:30 AM)",
                            "status": "pending",
                            "resolved": False
                        })
        
        # Missing Check-out
        if error_type in ["All", "Missing Check-out"]:
            if record.check_in_time and not record.check_out_time:
                errors.append({
                    "id": f"missing_out_{record.id}_{record.date.isoformat()}",
                    "date": record.date.isoformat(),
                    "student_id": attachee.username,
                    "student_name": attachee.full_name,
                    "error_type": "Missing Check-out",
                    "description": "Student checked in but forgot to check out.",
                    "status": "pending",
                    "resolved": False
                })
        
        # Absent
        if error_type in ["All", "Absent"]:
            if not record.check_in_time and record.status == "absent":
                errors.append({
                    "id": f"absent_{record.id}_{record.date.isoformat()}",
                    "date": record.date.isoformat(),
                    "student_id": attachee.username,
                    "student_name": attachee.full_name,
                    "error_type": "Absent",
                    "description": "Student was marked absent with no check-in record.",
                    "status": "pending",
                    "resolved": False
                })
    
    # Sort errors by date (newest first)
    errors.sort(key=lambda x: x["date"], reverse=True)
    
    # Get summary counts
    summary = {
        "face_recognition": len([e for e in errors if e["error_type"] == "Face Recognition"]),
        "late_check_in": len([e for e in errors if e["error_type"] == "Late Check-in"]),
        "missing_check_out": len([e for e in errors if e["error_type"] == "Missing Check-out"]),
        "absent": len([e for e in errors if e["error_type"] == "Absent"]),
        "total": len(errors)
    }
    
    # Return proper JSON response
    return JSONResponse(content={
        "errors": errors,
        "summary": summary,
        "total": len(errors),
        "success": True
    })


@app.get("/api/it-manager/attendance-errors/summary")
async def get_attendance_errors_summary(
    db: Session = Depends(get_db_local),
    current_user: User = Depends(get_current_user)
):
    """
    Get summary counts of attendance errors for the dashboard.
    """
    if current_user.role != "it_manager":
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Get today's date
    today = datetime.now().date()
    week_ago = today - timedelta(days=7)
    
    # Query attendance records for the last 7 days
    attendance_records = db.query(Attendance).filter(
        Attendance.date >= week_ago,
        Attendance.date <= today
    ).all()
    
    # Count errors
    face_issue_count = db.query(AttacheeProfile).filter(
        AttacheeProfile.face_recognition_issues > 0
    ).count()
    
    late_checkins = 0
    missing_checkouts = 0
    absent_count = 0
    
    for record in attendance_records:
        # Late check-ins (after 9:00 AM)
        if record.check_in_time:
            check_in_str = str(record.check_in_time)
            if ':' in check_in_str:
                parts = check_in_str.split(':')
                check_in_hour = int(parts[0])
                check_in_minute = int(parts[1]) if len(parts) > 1 else 0
                if check_in_hour > 7 or (check_in_hour == 7 and check_in_minute > 30):
                    late_checkins += 1
        
        # Missing check-outs
        if record.check_in_time and not record.check_out_time:
            missing_checkouts += 1
        
        # Absent
        if not record.check_in_time and record.status == "absent":
            absent_count += 1
    
    return {
        "face_recognition_issues": face_issue_count,
        "late_checkins": late_checkins,
        "missing_checkouts": missing_checkouts,
        "absent": absent_count,
        "total": face_issue_count + late_checkins + missing_checkouts + absent_count,
        "period": {
            "start": week_ago.isoformat(),
            "end": today.isoformat()
        }
    }


@app.post("/api/it-manager/attendance-errors/{error_id}/resolve")
async def resolve_attendance_error(
    error_id: str,
    resolution_note: str = None,
    db: Session = Depends(get_db_local),
    current_user: User = Depends(get_current_user)
):
    """
    Resolve an attendance error/issue.
    """
    if current_user.role != "it_manager":
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Parse error_id to determine type
    parts = error_id.split("_")
    
    if len(parts) < 2:
        raise HTTPException(status_code=400, detail="Invalid error ID format")
    
    error_type = parts[0]
    
    # Log the resolution
    system_log = SystemLog(
        user_id=current_user.id,
        action="resolve_attendance_error",
        details=f"Resolved error {error_id}: {resolution_note}",
        log_type="attendance",
        created_at=datetime.now()
    )
    db.add(system_log)
    db.commit()
    
    return {
        "success": True,
        "message": f"Error {error_id} marked as resolved",
        "resolved_by": current_user.full_name,
        "resolved_at": datetime.now().isoformat()
    }

# Add import at top of main.py
from pos_integration import POSIntegration

# Add these endpoints (anywhere in main.py, after other imports)

@app.post("/api/verify-transaction")
def verify_transaction(data: dict, db: Session = Depends(get_db_local)):
    """
    Verify M-Pesa transaction code from POS system
    Ensures each transaction code can only be used ONCE by ANY student
    """
    student_id = data.get('student_id')
    transaction_code = data.get('transaction_code')
    
    if not student_id or not transaction_code:
        raise HTTPException(status_code=400, detail="Student ID and transaction code required")
    
    # Convert to uppercase for consistency
    transaction_code = transaction_code.upper().strip()
    
    # Get student
    user = db.query(User).filter(User.id == student_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Student not found")
    
    # Check if this student is already verified
    if hasattr(user, 'transaction_verified') and user.transaction_verified:
        return {
            "verified": True,
            "already_verified": True,
            "amount_paid": getattr(user, 'amount_paid', 0),
            "message": "You have already verified your payment"
        }
    
    # CRITICAL: Check if this transaction code has already been used by ANY student
    # This prevents multiple students from using the same M-Pesa code
    existing_user = db.query(User).filter(
        User.transaction_code == transaction_code,
        User.transaction_verified == True
    ).first()
    
    if existing_user:
        return {
            "verified": False,
            "error": f"This transaction code has already been used by {existing_user.full_name} (Student ID: {existing_user.username}). Each M-Pesa transaction code can only be used once."
        }
    
    # Verify with POS system (check if transaction exists in POS database)
    result = POSIntegration.verify_mpesa_code(transaction_code, student_id)
    
    if result.get('verified'):
        # Update user record with transaction info
        user.transaction_verified = True
        user.transaction_code = transaction_code
        user.transaction_verified_at = datetime.now()
        user.amount_paid = result.get('amount_paid', 0)
        user.payment_reference = transaction_code
        db.commit()
        
        print(f"âœ… Student {student_id} ({user.username}) verified with M-Pesa code: {transaction_code}")
        print(f"   Amount paid: KES {result.get('amount_paid', 0):.2f}")
        print(f"   Receipt: {result.get('receipt_number')}")
        
        return {
            "verified": True,
            "amount_paid": result.get('amount_paid', 0),
            "payment_reference": transaction_code,
            "receipt_number": result.get('receipt_number'),
            "customer_name": result.get('customer_name'),
            "payment_date": result.get('payment_date')
        }
    else:
        return {
            "verified": False,
            "error": result.get('error', 'Invalid transaction code. Please check your M-Pesa message and try again.')
        }


@app.get("/api/check-transaction-status/{student_id}")
def check_transaction_status(student_id: int, db: Session = Depends(get_db_local)):
    """Check if a student has already verified a transaction"""
    user = db.query(User).filter(User.id == student_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "verified": getattr(user, 'transaction_verified', False),
        "amount_paid": getattr(user, 'amount_paid', 0),
        "transaction_code": getattr(user, 'transaction_code', None),
        "verified_at": getattr(user, 'transaction_verified_at', None),
        "payment_reference": getattr(user, 'payment_reference', None)
    }


@app.get("/api/check-transaction-code-usage/{transaction_code}")
def check_transaction_code_usage(transaction_code: str, db: Session = Depends(get_db_local)):
    """
    Admin endpoint to check if a transaction code has already been used
    Useful for debugging and verification
    """
    transaction_code = transaction_code.upper().strip()
    
    user = db.query(User).filter(
        User.transaction_code == transaction_code,
        User.transaction_verified == True
    ).first()
    
    if user:
        return {
            "used": True,
            "used_by": user.full_name,
            "used_by_username": user.username,
            "used_by_id": user.id,
            "used_at": user.transaction_verified_at.isoformat() if user.transaction_verified_at else None,
            "amount_paid": user.amount_paid,
            "payment_reference": user.payment_reference
        }
    else:
        return {
            "used": False,
            "message": "Transaction code not found or not yet used"
        }


@app.get("/api/unused-transaction-codes")
def get_unused_transaction_codes(db: Session = Depends(get_db_local)):
    """
    Admin endpoint to get all transaction codes that haven't been used yet
    (Useful for monitoring which receipts are still valid)
    """
    # Get all used transaction codes
    used_codes = db.query(User.transaction_code).filter(
        User.transaction_verified == True,
        User.transaction_code.isnot(None)
    ).all()
    
    used_code_list = [code[0] for code in used_codes if code[0]]
    
    # Query POS database for all transaction codes and filter out used ones
    result = POSIntegration.get_all_transaction_codes()
    
    unused_codes = []
    for code in result.get('transaction_codes', []):
        if code not in used_code_list:
            unused_codes.append(code)
    
    return {
        "total_in_pos": len(result.get('transaction_codes', [])),
        "used_count": len(used_code_list),
        "unused_count": len(unused_codes),
        "unused_codes": unused_codes[:100]  # Limit to 100 for performance
    } 

# ==================== TASK FILE UPLOAD ENDPOINTS ====================

@app.post("/api/attachee/tasks/{task_id}/upload-report")
async def upload_task_report(
    task_id: int,
    user_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db_local)
):
    """Attachee uploads a report file to complete a task"""
    
    # Verify task exists and belongs to this user
    task = db.query(Task).filter(Task.id == task_id, Task.assigned_to_id == user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if task.status == "completed":
        raise HTTPException(status_code=400, detail="Task already completed")
    
    # Validate file type
    allowed_types = ['application/pdf', 'application/msword', 
                     'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                     'image/jpeg', 'image/png', 'image/jpg']
    
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Only PDF, Word documents, and images are allowed")
    
    # Create uploads/tasks directory
    uploads_dir = Config.get_uploads_path() / "tasks"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    
    # Save file
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_filename = f"task_{task_id}_{user_id}_{timestamp}.pdf"
    if file.filename.endswith('.docx'):
        safe_filename = safe_filename.replace('.pdf', '.docx')
    elif file.filename.endswith('.doc'):
        safe_filename = safe_filename.replace('.pdf', '.doc')
    elif file.filename.endswith(('.jpg', '.jpeg', '.png')):
        safe_filename = safe_filename.replace('.pdf', '.jpg')
    
    file_path = uploads_dir / safe_filename
    
    content = await file.read()
    with open(file_path, "wb") as buffer:
        buffer.write(content)
    
    # Update task
    task.status = "completed"
    task.completed_at = datetime.now()
    task.report_path = str(file_path)
    task.report_filename = file.filename
    
    db.commit()
    
    # Notify supervisor
    supervisor = db.query(User).filter(User.id == task.assigned_by_id).first()
    if supervisor:
        send_push_notification(
            supervisor.id,
            "ðŸ“„ Task Report Submitted",
            f"Student {task.student_name if hasattr(task, 'student_name') else 'Unknown'} has submitted a report for task: {task.title}"
        )
        
        notification = Notification(
            user_id=supervisor.id,
            title="Task Report Submitted",
            message=f"A report has been uploaded for task: {task.title}. Please review and provide feedback.",
            type="task_report"
        )
        db.add(notification)
        db.commit()
    
    return {
        "message": "Report uploaded successfully",
        "task_id": task_id,
        "file_path": str(file_path),
        "status": "completed"
    }


@app.get("/api/supervisor/task-reports/{supervisor_id}")
def get_pending_task_reports(supervisor_id: int, db: Session = Depends(get_db_local)):
    """Supervisor gets all completed tasks awaiting review (with uploaded reports)"""
    
    # Get all tasks created by this supervisor that are completed but not reviewed
    tasks = db.query(Task).filter(
        Task.assigned_by_id == supervisor_id,
        Task.status == "completed",
        Task.reviewed == False
    ).order_by(Task.completed_at.desc()).all()
    
    result = []
    for task in tasks:
        student = db.query(User).filter(User.id == task.assigned_to_id).first()
        
        result.append({
            "id": task.id,
            "student_name": student.full_name if student else "Unknown",
            "student_id": task.assigned_to_id,
            "title": task.title,
            "description": task.description,
            "priority": task.priority,
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "report_path": task.report_path,
            "report_filename": task.report_filename,
            "feedback": task.feedback,
            "status": task.status
        })
    
    return result


@app.post("/api/supervisor/task-report/{task_id}/review")
def review_task_report(
    task_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Supervisor reviews a submitted task report and provides feedback"""
    
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    feedback = data.get('feedback', '')
    rating = data.get('rating', 0)
    
    task.feedback = feedback
    task.rating = rating
    task.reviewed = True
    task.reviewed_at = datetime.now()
    
    db.commit()
    
    # Notify student
    background_tasks.add_task(
        send_push_notification,
        task.assigned_to_id,
        "ðŸ“ Task Feedback Received",
        f"Your supervisor has provided feedback on your task report: {task.title}"
    )
    
    notification = Notification(
        user_id=task.assigned_to_id,
        title="Task Feedback",
        message=f"Feedback received for task: {task.title}\n\n{feedback}",
        type="task_feedback"
    )
    db.add(notification)
    db.commit()
    
    return {"message": "Feedback submitted successfully", "task_id": task_id}


@app.get("/api/supervisor/task-report/download/{task_id}")
def download_task_report(task_id: int, db: Session = Depends(get_db_local)):
    """Download the report file for a task"""
    
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if not task.report_path or not os.path.exists(task.report_path):
        raise HTTPException(status_code=404, detail="Report file not found")
    
    return FileResponse(
        task.report_path,
        media_type='application/octet-stream',
        filename=task.report_filename or f"task_report_{task_id}.pdf"
    )


@app.get("/api/attachee/tasks/{task_id}/report")
def get_task_report_info(task_id: int, user_id: int, db: Session = Depends(get_db_local)):
    """Get task report information for attachee"""
    
    task = db.query(Task).filter(Task.id == task_id, Task.assigned_to_id == user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return {
        "has_report": task.report_path is not None,
        "report_filename": task.report_filename,
        "report_path": task.report_path,
        "feedback": task.feedback,
        "reviewed": task.reviewed if hasattr(task, 'reviewed') else False
    } 

# ==================== RESOURCE MANAGEMENT ENDPOINTS ====================

# Add these models to your models.py:
"""
class Resource(Base):
    __tablename__ = "resources"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    category = Column(String(100), nullable=False)
    condition = Column(String(50), default="Good")
    total_quantity = Column(Integer, default=0)
    available_quantity = Column(Integer, default=0)
    times_issued = Column(Integer, default=0)
    last_issued_date = Column(DateTime, nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    is_active = Column(Boolean, default=True)

class ResourceAllocation(Base):
    __tablename__ = "resource_allocations"
    
    id = Column(Integer, primary_key=True, index=True)
    resource_id = Column(Integer, ForeignKey("resources.id"), nullable=False)
    attachee_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    issued_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    issued_date = Column(DateTime, default=datetime.now)
    expected_return_date = Column(DateTime, nullable=False)
    actual_return_date = Column(DateTime, nullable=True)
    status = Column(String(50), default="issued")  # issued, returned, overdue
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
"""

# Add these endpoints to main.py:

@app.get("/api/resources")
def get_all_resources(db: Session = Depends(get_db_local)):
    """Get all resources in inventory"""
    resources = db.query(Resource).filter(Resource.is_active == True).order_by(Resource.name).all()
    
    result = []
    for r in resources:
        result.append({
            "id": r.id,
            "name": r.name,
            "category": r.category,
            "condition": r.condition,
            "total_quantity": r.total_quantity,
            "available_quantity": r.available_quantity,
            "times_issued": r.times_issued,
            "last_issued_date": r.last_issued_date.strftime("%b %d, %Y") if r.last_issued_date else "Never",
            "description": r.description
        })
    
    return result


@app.post("/api/resources")
def create_resource(data: dict, db: Session = Depends(get_db_local)):
    """Create a new resource"""
    
    resource = Resource(
        name=data.get('name'),
        category=data.get('category'),
        condition=data.get('condition', 'Good'),
        total_quantity=data.get('total_quantity', 0),
        available_quantity=data.get('total_quantity', 0),
        description=data.get('description', '')
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)
    
    return {"message": "Resource created", "resource_id": resource.id}


@app.put("/api/resources/{resource_id}")
def update_resource(resource_id: int, data: dict, db: Session = Depends(get_db_local)):
    """Update a resource"""
    
    resource = db.query(Resource).filter(Resource.id == resource_id).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    
    if 'name' in data:
        resource.name = data['name']
    if 'category' in data:
        resource.category = data['category']
    if 'condition' in data:
        resource.condition = data['condition']
    if 'total_quantity' in data:
        diff = data['total_quantity'] - resource.total_quantity
        resource.total_quantity = data['total_quantity']
        resource.available_quantity += diff
    if 'description' in data:
        resource.description = data['description']
    
    resource.updated_at = datetime.now()
    db.commit()
    
    return {"message": "Resource updated"}


@app.delete("/api/resources/{resource_id}")
def delete_resource(resource_id: int, db: Session = Depends(get_db_local)):
    """Soft delete a resource"""
    
    resource = db.query(Resource).filter(Resource.id == resource_id).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    
    resource.is_active = False
    db.commit()
    
    return {"message": "Resource deleted"}


@app.get("/api/resource-allocations")
def get_all_allocations(db: Session = Depends(get_db_local)):
    """Get all resource allocations"""
    
    allocations = db.query(ResourceAllocation).order_by(ResourceAllocation.issued_date.desc()).all()
    
    result = []
    for a in allocations:
        resource = db.query(Resource).filter(Resource.id == a.resource_id).first()
        attachee = db.query(User).filter(User.id == a.attachee_id).first()
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == a.attachee_id).first()
        issuer = db.query(User).filter(User.id == a.issued_by).first()
        
        # Determine status display
        if a.actual_return_date:
            status = "Returned"
        elif datetime.now() > a.expected_return_date:
            status = "Overdue"
        else:
            status = "In Use"
        
        result.append({
            "id": a.id,
            "resource_id": a.resource_id,
            "resource_name": resource.name if resource else "Unknown",
            "attachee_id": a.attachee_id,
            "attachee_name": attachee.full_name if attachee else "Unknown",
            "student_id": profile.student_id if profile else "N/A",
            "department": profile.department if profile else "Not assigned",
            "issued_by": issuer.full_name if issuer else "System",
            "issued_date": a.issued_date.strftime("%b %d, %Y"),
            "expected_return_date": a.expected_return_date.strftime("%b %d, %Y"),
            "actual_return_date": a.actual_return_date.strftime("%b %d, %Y") if a.actual_return_date else None,
            "status": status,
            "notes": a.notes or ""
        })
    
    return result


@app.post("/api/resource-allocations")
def create_allocation(data: dict, background_tasks: BackgroundTasks, db: Session = Depends(get_db_local)):
    """Allocate a resource to an attachee"""
    
    resource_id = data.get('resource_id')
    attachee_id = data.get('attachee_id')
    issued_by = data.get('issued_by')
    expected_return_date = data.get('expected_return_date')
    notes = data.get('notes', '')
    
    resource = db.query(Resource).filter(Resource.id == resource_id).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    
    if resource.available_quantity <= 0:
        raise HTTPException(status_code=400, detail="No available quantity for this resource")
    
    # Create allocation
    allocation = ResourceAllocation(
        resource_id=resource_id,
        attachee_id=attachee_id,
        issued_by=issued_by,
        expected_return_date=datetime.fromisoformat(expected_return_date),
        notes=notes
    )
    db.add(allocation)
    
    # Update resource
    resource.available_quantity -= 1
    resource.times_issued += 1
    resource.last_issued_date = datetime.now()
    
    db.commit()
    
    # Notify attachee
    background_tasks.add_task(
        send_push_notification,
        attachee_id,
        "ðŸ“¦ Resource Allocated",
        f"You have been allocated: {resource.name}. Expected return: {expected_return_date}"
    )
    
    return {"message": "Resource allocated successfully", "allocation_id": allocation.id}


@app.post("/api/resource-allocations/{allocation_id}/return")
def return_resource(allocation_id: int, data: dict, background_tasks: BackgroundTasks, db: Session = Depends(get_db_local)):
    """Return a resource"""
    
    allocation = db.query(ResourceAllocation).filter(ResourceAllocation.id == allocation_id).first()
    if not allocation:
        raise HTTPException(status_code=404, detail="Allocation not found")
    
    if allocation.actual_return_date:
        raise HTTPException(status_code=400, detail="Resource already returned")
    
    allocation.actual_return_date = datetime.now()
    allocation.updated_at = datetime.now()
    
    # Update resource availability
    resource = db.query(Resource).filter(Resource.id == allocation.resource_id).first()
    if resource:
        resource.available_quantity += 1
    
    db.commit()
    
    # Notify attachee
    background_tasks.add_task(
        send_push_notification,
        allocation.attachee_id,
        "âœ… Resource Returned",
        f"Resource '{resource.name if resource else 'Unknown'}' has been marked as returned."
    )
    
    return {"message": "Resource returned successfully"}


@app.get("/api/attachee/resources/{attachee_id}")
def get_attachee_resources(attachee_id: int, db: Session = Depends(get_db_local)):
    """Get resources allocated to a specific attachee"""
    
    allocations = db.query(ResourceAllocation).filter(
        ResourceAllocation.attachee_id == attachee_id,
        ResourceAllocation.actual_return_date == None
    ).all()
    
    result = []
    for a in allocations:
        resource = db.query(Resource).filter(Resource.id == a.resource_id).first()
        status = "Overdue" if datetime.now() > a.expected_return_date else "In Use"
        
        result.append({
            "id": a.id,
            "resource_name": resource.name if resource else "Unknown",
            "issued_date": a.issued_date.strftime("%b %d, %Y"),
            "expected_return_date": a.expected_return_date.strftime("%b %d, %Y"),
            "status": status,
            "notes": a.notes or ""
        })
    
    return result


@app.get("/api/resource-categories")
def get_resource_categories(db: Session = Depends(get_db_local)):
    """Get all resource categories"""
    
    categories = db.query(Resource.category).distinct().all()
    return [c[0] for c in categories if c[0]]    

@app.get("/api/disciplinary/cases")
def get_disciplinary_cases(db: Session = Depends(get_db_local)):
    """Get all disciplinary cases"""
    cases = db.query(DisciplinaryCase).order_by(DisciplinaryCase.created_at.desc()).all()
    
    result = []
    for case in cases:
        target_name = "Group Case"
        target_id = None
        if not case.is_group and case.target_user_id:
            user = db.query(User).filter(User.id == case.target_user_id).first()
            target_name = user.full_name if user else "Unknown"
            profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == case.target_user_id).first()
            target_id = profile.student_id if profile else None
        elif case.is_group:
            target_name = case.target_group
        
        reporter = db.query(User).filter(User.id == case.reported_by).first()
        
        result.append({
            "id": case.id,
            "target": target_name,
            "target_id": target_id,
            "is_group": case.is_group,
            "reported_by": reporter.full_name if reporter else "Unknown",
            "reporter_role": reporter.role if reporter else "System",
            "issue_type": case.issue_type,
            "description": case.description,
            "date": case.created_at.strftime("%b %d, %Y"),
            "status": case.status,
            "resolution": case.resolution
        })
    
    return result


@app.post("/api/disciplinary/cases")
def create_disciplinary_case(data: dict, db: Session = Depends(get_db_local)):
    """Create a new disciplinary case"""
    
    case = DisciplinaryCase(
        target_user_id=data.get('target_user_id'),
        target_group=data.get('target_group'),
        is_group=data.get('is_group', False),
        reported_by=data.get('reported_by'),
        issue_type=data.get('issue_type'),
        description=data.get('description'),
        status=data.get('status', 'Open')
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    
    return {"message": "Case created", "case_id": case.id}


@app.put("/api/disciplinary/cases/{case_id}")
def update_disciplinary_case(case_id: int, data: dict, db: Session = Depends(get_db_local)):
    """Update a disciplinary case status/resolution"""
    
    case = db.query(DisciplinaryCase).filter(DisciplinaryCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    if 'status' in data:
        case.status = data['status']
    if 'resolution' in data:
        case.resolution = data['resolution']
    
    case.updated_at = datetime.now()
    db.commit()
    
    return {"message": "Case updated"}


@app.get("/api/compliance/records")
def get_compliance_records(db: Session = Depends(get_db_local)):
    """Get compliance records"""
    records = db.query(ComplianceRecord).order_by(ComplianceRecord.deadline).all()
    
    result = []
    for record in records:
        completion_pct = int((record.completed_count / record.total_count) * 100) if record.total_count > 0 else 0
        status = "Compliant" if completion_pct == 100 else ("Action Required" if completion_pct >= 70 else "In Progress")
        
        result.append({
            "id": record.id,
            "policy_name": record.policy_name,
            "target_group": record.target_group,
            "completion_pct": completion_pct,
            "deadline": record.deadline.strftime("%b %d, %Y"),
            "status": status
        })
    
    return result


@app.post("/api/compliance/records")
def create_compliance_record(data: dict, db: Session = Depends(get_db_local)):
    """Create a new compliance record"""
    deadline_value = data.get("deadline")
    if not deadline_value:
        raise HTTPException(status_code=400, detail="Deadline is required")

    try:
        deadline_date = date.fromisoformat(deadline_value)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid deadline format. Use YYYY-MM-DD")

    record = ComplianceRecord(
        policy_name=data.get("policy_name", "").strip(),
        target_group=data.get("target_group_label", data.get("target_group", "")).strip(),
        completed_count=int(data.get("completed_count", 0) or 0),
        total_count=max(1, int(data.get("total_count", 1) or 1)),
        deadline=deadline_date,
        status=data.get("status", "In Progress"),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"message": "Compliance record created", "record_id": record.id}


@app.get("/api/commendations")
def get_commendations(db: Session = Depends(get_db_local)):
    """Get commendations"""
    commendations = db.query(Commendation).order_by(Commendation.created_at.desc()).all()
    
    result = []
    for comm in commendations:
        user = db.query(User).filter(User.id == comm.user_id).first()
        creator = db.query(User).filter(User.id == comm.created_by).first()
        
        result.append({
            "id": comm.id,
            "name": user.full_name if user else "Unknown",
            "department": comm.department or (user.role if user else "N/A"),
            "title": comm.title,
            "period": comm.period,
            "reason": comm.reason,
            "created_by": creator.full_name if creator else "System",
            "created_at": comm.created_at.strftime("%b %d, %Y")
        })
    
    return result


@app.post("/api/commendations")
def create_commendation(data: dict, db: Session = Depends(get_db_local)):
    """Create a new commendation"""
    user_id = data.get("commendation_user_id") or data.get("user_id")
    created_by = data.get("reported_by") or data.get("created_by")

    if not user_id:
        raise HTTPException(status_code=400, detail="Recipient is required")
    if not created_by:
        raise HTTPException(status_code=400, detail="Creator is required")

    commendation = Commendation(
        user_id=int(user_id),
        title=(data.get("commendation_title") or data.get("title") or "").strip(),
        period=(data.get("period") or "").strip(),
        reason=(data.get("description") or data.get("reason") or "").strip(),
        department=(data.get("target_group_label") or data.get("department") or "").strip() or None,
        created_by=int(created_by),
    )
    db.add(commendation)
    db.commit()
    db.refresh(commendation)
    return {"message": "Commendation created", "commendation_id": commendation.id}

# ==================== CHALLENGES & RISK MANAGEMENT ENDPOINTS ====================

def _parse_challenge_meta(raw_attachments):
    if not raw_attachments:
        return {}
    try:
        parsed = json.loads(raw_attachments)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _build_challenge_payload(challenge, db: Session):
    reporter = db.query(User).filter(User.id == challenge.reported_by).first()
    resolver = db.query(User).filter(User.id == challenge.resolved_by).first() if challenge.resolved_by else None
    meta = _parse_challenge_meta(challenge.attachments)
    implemented_by_id = meta.get("implemented_by")
    implemented_by_user = None
    try:
        if implemented_by_id:
            implemented_by_user = db.query(User).filter(User.id == int(implemented_by_id)).first()
    except Exception:
        implemented_by_user = None

    return {
        "id": challenge.id,
        "title": challenge.title,
        "description": challenge.description,
        "category": challenge.category,
        "severity": challenge.severity,
        "status": challenge.status,
        "reporter": reporter.full_name if reporter else "Unknown",
        "reported_by": reporter.full_name if reporter else "Unknown",
        "reported_at": challenge.reported_at.strftime("%b %d, %Y"),
        "resolved_at": challenge.resolved_at.strftime("%b %d, %Y") if challenge.resolved_at else None,
        "resolved_by": resolver.full_name if resolver else None,
        "resolution_notes": challenge.resolution_notes,
        "forwarded_by": meta.get("forwarded_by"),
        "forwarded_at": meta.get("forwarded_at"),
        "coordinator_notes": meta.get("coordinator_notes", ""),
        "supervisor_notes": meta.get("supervisor_notes", ""),
        "implemented_by": implemented_by_user.full_name if implemented_by_user else meta.get("implemented_by"),
        "implemented_at": meta.get("implemented_at"),
        "reviewed_at": meta.get("reviewed_at"),
    }

@app.get("/api/challenges")
def get_all_challenges(db: Session = Depends(get_db_local)):
    """Get all reported challenges"""
    challenges = db.query(Challenge).order_by(Challenge.reported_at.desc()).all()
    
    return [_build_challenge_payload(c, db) for c in challenges]


@app.get("/api/user/challenges/{user_id}")
def get_user_challenges(user_id: int, db: Session = Depends(get_db_local)):
    """Get challenges submitted by a specific user."""
    challenges = db.query(Challenge).filter(
        Challenge.reported_by == user_id
    ).order_by(Challenge.reported_at.desc()).all()

    return [_build_challenge_payload(challenge, db) for challenge in challenges]


@app.get("/api/coordinator/challenges")
def get_coordinator_challenges(db: Session = Depends(get_db_local)):
    """Get all challenges for coordinator review."""
    return get_all_challenges(db)


@app.get("/api/supervisor/challenges")
def get_supervisor_challenges(db: Session = Depends(get_db_local)):
    """Get challenges that have been forwarded to supervisors."""
    challenges = db.query(Challenge).filter(
        Challenge.status == "Forwarded to Supervisor"
    ).order_by(Challenge.reported_at.desc()).all()

    return [_build_challenge_payload(challenge, db) for challenge in challenges]


@app.post("/api/challenges")
def create_challenge(data: dict, db: Session = Depends(get_db_local)):
    """Create a new challenge report"""
    reporter_id = data.get("reported_by") or data.get("user_id")
    if not reporter_id:
        raise HTTPException(status_code=400, detail="reported_by is required")
    if not data.get("title"):
        raise HTTPException(status_code=400, detail="title is required")
    if not data.get("description"):
        raise HTTPException(status_code=400, detail="description is required")

    challenge = Challenge(
        title=data.get('title'),
        description=data.get('description'),
        category=data.get('category'),
        severity=data.get('severity', 'Medium'),
        status="New",
        reported_by=reporter_id,
        attachments=json.dumps({
            "source": "web",
            "coordinator_notes": "",
            "supervisor_notes": ""
        })
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)

    coordinators = db.query(User).filter(User.role == "coordinator").all()
    for coordinator in coordinators:
        notification = Notification(
            user_id=coordinator.id,
            title="New Challenge Reported",
            message=f"A new challenge was reported in category: {challenge.category}",
            type="challenge"
        )
        db.add(notification)
        try:
            send_push_notification(
                coordinator.id,
                "ðŸš§ New Challenge Reported",
                f"A new challenge was reported in category: {challenge.category}"
            )
        except Exception:
            pass

    db.commit()
    
    return {"message": "Challenge reported", "challenge_id": challenge.id}


@app.put("/api/challenges/{challenge_id}/forward")
def forward_challenge(challenge_id: int, data: dict, db: Session = Depends(get_db_local)):
    """Forward a challenge from coordinator to supervisor."""
    challenge = db.query(Challenge).filter(Challenge.id == challenge_id).first()
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")

    if challenge.status not in ["New", "Open"]:
        raise HTTPException(status_code=400, detail="Only new challenges can be forwarded")

    meta = _parse_challenge_meta(challenge.attachments)
    meta["forwarded_by"] = data.get("forwarded_by")
    meta["forwarded_at"] = datetime.now().strftime("%b %d, %Y")
    meta["coordinator_notes"] = data.get("notes", data.get("response", ""))
    challenge.attachments = json.dumps(meta)
    challenge.status = "Forwarded to Supervisor"

    db.commit()

    supervisors = db.query(User).filter(User.role == "supervisor").all()
    for supervisor in supervisors:
        notification = Notification(
            user_id=supervisor.id,
            title="Challenge Forwarded for Review",
            message=f"A coordinator forwarded a challenge in category: {challenge.category}",
            type="challenge"
        )
        db.add(notification)
        try:
            send_push_notification(
                supervisor.id,
                "ðŸš§ Challenge Forwarded",
                f"A coordinator forwarded a challenge in category: {challenge.category}"
            )
        except Exception:
            pass

    if challenge.reported_by:
        try:
            send_push_notification(
                challenge.reported_by,
                "ðŸš§ Challenge Forwarded",
                f"Your challenge '{challenge.title}' has been forwarded for review."
            )
        except Exception:
            pass
        notification = Notification(
            user_id=challenge.reported_by,
            title="Challenge Forwarded",
            message=f"Your challenge '{challenge.title}' has been forwarded for review.",
            type="challenge"
        )
        db.add(notification)

    db.commit()
    return {"message": "Challenge forwarded to supervisor"}


@app.put("/api/challenges/{challenge_id}/review")
def review_challenge(challenge_id: int, data: dict, db: Session = Depends(get_db_local)):
    """Mark a challenge as under review."""
    challenge = db.query(Challenge).filter(Challenge.id == challenge_id).first()
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")

    if challenge.status != "Forwarded to Supervisor":
        raise HTTPException(status_code=400, detail="Only forwarded challenges can be reviewed")

    meta = _parse_challenge_meta(challenge.attachments)
    meta["reviewed_by"] = data.get("reviewed_by")
    meta["reviewed_at"] = datetime.now().strftime("%b %d, %Y")
    meta["supervisor_notes"] = data.get("response", data.get("notes", ""))
    challenge.attachments = json.dumps(meta)
    challenge.status = "Under Review"

    db.commit()

    if challenge.reported_by:
        try:
            send_push_notification(
                challenge.reported_by,
                "ðŸš§ Challenge Reviewed",
                f"Your challenge '{challenge.title}' is under review."
            )
        except Exception:
            pass
        notification = Notification(
            user_id=challenge.reported_by,
            title="Challenge Reviewed",
            message=f"Your challenge '{challenge.title}' is under review.",
            type="challenge"
        )
        db.add(notification)
        db.commit()

    return {"message": "Challenge marked as under review"}


@app.put("/api/challenges/{challenge_id}/implement")
def implement_challenge(challenge_id: int, data: dict, db: Session = Depends(get_db_local)):
    """Mark a challenge as implemented."""
    challenge = db.query(Challenge).filter(Challenge.id == challenge_id).first()
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")

    if challenge.status not in ["Forwarded to Supervisor", "Under Review"]:
        raise HTTPException(status_code=400, detail="Only forwarded challenges can be implemented")

    meta = _parse_challenge_meta(challenge.attachments)
    meta["implemented_by"] = data.get("implemented_by")
    meta["implemented_at"] = datetime.now().strftime("%b %d, %Y")
    meta["supervisor_notes"] = data.get("response", data.get("notes", ""))
    challenge.attachments = json.dumps(meta)
    challenge.status = "Implemented"

    db.commit()

    if challenge.reported_by:
        try:
            send_push_notification(
                challenge.reported_by,
                "âœ… Challenge Implemented",
                f"Your challenge '{challenge.title}' has been implemented."
            )
        except Exception:
            pass
        notification = Notification(
            user_id=challenge.reported_by,
            title="Challenge Implemented",
            message=f"Your challenge '{challenge.title}' has been implemented.",
            type="challenge"
        )
        db.add(notification)
        db.commit()

    return {"message": "Challenge marked as implemented"}


@app.put("/api/challenges/{challenge_id}/resolve")
def resolve_challenge(challenge_id: int, data: dict, db: Session = Depends(get_db_local)):
    """Resolve a challenge"""
    
    challenge = db.query(Challenge).filter(Challenge.id == challenge_id).first()
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    
    challenge.status = "Resolved"
    challenge.resolved_at = datetime.now()
    challenge.resolved_by = data.get('resolved_by')
    challenge.resolution_notes = data.get('resolution_notes', '')
    meta = _parse_challenge_meta(challenge.attachments)
    meta["supervisor_notes"] = data.get("resolution_notes", meta.get("supervisor_notes", ""))
    meta["resolved_at"] = challenge.resolved_at.strftime("%b %d, %Y")
    meta["resolved_by"] = data.get('resolved_by')
    challenge.attachments = json.dumps(meta)
    db.commit()

    if challenge.reported_by:
        try:
            send_push_notification(
                challenge.reported_by,
                "âœ… Challenge Resolved",
                f"Your challenge '{challenge.title}' has been resolved."
            )
        except Exception:
            pass
        notification = Notification(
            user_id=challenge.reported_by,
            title="Challenge Resolved",
            message=f"Your challenge '{challenge.title}' has been resolved.",
            type="challenge"
        )
        db.add(notification)
        db.commit()
    
    return {"message": "Challenge resolved"}


@app.get("/api/risks")
def get_all_risks(db: Session = Depends(get_db_local)):
    """Get all program risks"""
    risks = db.query(Risk).order_by(Risk.created_at.desc()).all()
    
    result = []
    for r in risks:
        creator = db.query(User).filter(User.id == r.created_by).first()
        
        result.append({
            "id": r.id,
            "title": r.title,
            "description": r.description,
            "impact": r.impact,
            "probability": r.probability,
            "owner": r.owner,
            "status": r.status,
            "mitigation_plan": r.mitigation_plan,
            "created_by": creator.full_name if creator else "Unknown",
            "created_at": r.created_at.strftime("%b %d, %Y")
        })
    
    return result


@app.post("/api/risks")
def create_risk(data: dict, db: Session = Depends(get_db_local)):
    """Create a new risk"""
    
    risk = Risk(
        title=data.get('title'),
        description=data.get('description'),
        impact=data.get('impact', 'Medium'),
        probability=data.get('probability', 'Medium'),
        owner=data.get('owner'),
        status="Active",
        created_by=data.get('created_by')
    )
    db.add(risk)
    db.commit()
    db.refresh(risk)
    
    return {"message": "Risk created", "risk_id": risk.id}


@app.put("/api/risks/{risk_id}")
def update_risk(risk_id: int, data: dict, db: Session = Depends(get_db_local)):
    """Update a risk"""
    
    risk = db.query(Risk).filter(Risk.id == risk_id).first()
    if not risk:
        raise HTTPException(status_code=404, detail="Risk not found")
    
    if 'status' in data:
        risk.status = data['status']
    if 'mitigation_plan' in data:
        risk.mitigation_plan = data['mitigation_plan']
    
    risk.updated_at = datetime.now()
    db.commit()
    
    return {"message": "Risk updated"}


@app.get("/api/mitigation-plans")
def get_mitigation_plans(db: Session = Depends(get_db_local)):
    """Get all mitigation plans"""
    plans = db.query(MitigationPlan).order_by(MitigationPlan.deadline).all()
    
    result = []
    for p in plans:
        creator = db.query(User).filter(User.id == p.created_by).first()
        linked_issue = ""
        
        if p.challenge_id:
            challenge = db.query(Challenge).filter(Challenge.id == p.challenge_id).first()
            if challenge:
                linked_issue = f"Challenge: {challenge.title}"
        elif p.risk_id:
            risk = db.query(Risk).filter(Risk.id == p.risk_id).first()
            if risk:
                linked_issue = f"Risk: {risk.title}"
        
        result.append({
            "id": p.id,
            "title": p.title,
            "description": p.description,
            "linked_issue": linked_issue,
            "owner": p.owner,
            "progress_percent": p.progress_percent,
            "deadline": p.deadline.strftime("%b %d, %Y"),
            "status": p.status,
            "created_by": creator.full_name if creator else "Unknown"
        })
    
    return result


@app.post("/api/mitigation-plans")
def create_mitigation_plan(data: dict, db: Session = Depends(get_db_local)):
    """Create a new mitigation plan"""
    
    plan = MitigationPlan(
        title=data.get('title'),
        description=data.get('description'),
        challenge_id=data.get('challenge_id'),
        risk_id=data.get('risk_id'),
        owner=data.get('owner'),
        progress_percent=0,
        deadline=datetime.fromisoformat(data.get('deadline')).date(),
        status="Not Started",
        created_by=data.get('created_by')
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    
    return {"message": "Mitigation plan created", "plan_id": plan.id}


@app.put("/api/mitigation-plans/{plan_id}/progress")
def update_mitigation_progress(plan_id: int, data: dict, db: Session = Depends(get_db_local)):
    """Update mitigation plan progress"""
    
    plan = db.query(MitigationPlan).filter(MitigationPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    plan.progress_percent = data.get('progress_percent', plan.progress_percent)
    if plan.progress_percent == 100:
        plan.status = "Completed"
    elif plan.progress_percent > 0:
        plan.status = "In Progress"
    
    plan.updated_at = datetime.now()
    db.commit()
    
    return {"message": "Progress updated"}   

# ==================== SUGGESTION MANAGEMENT ENDPOINTS ====================

@app.get("/api/suggestions")
def get_all_suggestions(db: Session = Depends(get_db_local)):
    """Get all suggestions (for coordinators/supervisors)"""
    suggestions = db.query(Suggestion).order_by(Suggestion.created_at.desc()).all()
    
    result = []
    for s in suggestions:
        author_name = "Anonymous" if s.is_anonymous else (s.user.full_name if s.user else "Unknown")
        
        result.append({
            "id": s.id,
            "author": author_name,
            "category": s.category,
            "content": s.content,
            "status": s.status,
            "is_anonymous": s.is_anonymous,
            "created_at": s.created_at.strftime("%b %d, %Y"),
            "response": s.response,
            "reviewed_at": s.reviewed_at.strftime("%b %d, %Y") if s.reviewed_at else None,
            "implemented_at": s.implemented_at.strftime("%b %d, %Y") if s.implemented_at else None
        })
    
    return result


@app.get("/api/suggestions/{user_id}")
def get_user_suggestions(user_id: int, db: Session = Depends(get_db_local)):
    """Get suggestions submitted by a specific user"""
    suggestions = db.query(Suggestion).filter(
        Suggestion.user_id == user_id,
        Suggestion.is_anonymous == False
    ).order_by(Suggestion.created_at.desc()).all()
    
    result = []
    for s in suggestions:
        result.append({
            "id": s.id,
            "category": s.category,
            "content": s.content,
            "status": s.status,
            "created_at": s.created_at.strftime("%b %d, %Y"),
            "response": s.response
        })
    
    return result


@app.post("/api/suggestions")
def create_suggestion(data: dict, db: Session = Depends(get_db_local)):
    """Create a new suggestion"""
    
    user_id = data.get('user_id') if not data.get('is_anonymous') else None
    
    suggestion = Suggestion(
        content=data.get('content'),
        category=data.get('category', 'General'),
        is_anonymous=data.get('is_anonymous', False),
        user_id=user_id,
        status="New"
    )
    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)
    
    # Notify coordinators about new suggestion
    coordinators = db.query(User).filter(User.role == "coordinator").all()
    for coord in coordinators:
        notification = Notification(
            user_id=coord.id,
            title="New Suggestion Submitted",
            message=f"A new suggestion has been submitted in category: {suggestion.category}",
            type="suggestion"
        )
        db.add(notification)
        try:
            send_push_notification(
                coord.id,
                "ðŸ“ New Suggestion Submitted",
                f"A new suggestion has been submitted in category: {suggestion.category}"
            )
        except Exception:
            pass
    
    db.commit()
    
    return {"message": "Suggestion submitted", "suggestion_id": suggestion.id}


@app.get("/api/coordinator/suggestions")
def get_coordinator_suggestions(db: Session = Depends(get_db_local)):
    """Get all suggestions for coordinator review."""
    return get_all_suggestions(db)


@app.get("/api/supervisor/suggestions")
def get_supervisor_suggestions(db: Session = Depends(get_db_local)):
    """Get only suggestions that have been forwarded to supervisors."""
    suggestions = db.query(Suggestion).filter(
        Suggestion.status != "New"
    ).order_by(Suggestion.created_at.desc()).all()

    result = []
    for s in suggestions:
        author_name = "Anonymous" if s.is_anonymous else (s.user.full_name if s.user else "Unknown")

        result.append({
            "id": s.id,
            "author": author_name,
            "category": s.category,
            "content": s.content,
            "status": s.status,
            "is_anonymous": s.is_anonymous,
            "created_at": s.created_at.strftime("%b %d, %Y"),
            "response": s.response,
            "reviewed_at": s.reviewed_at.strftime("%b %d, %Y") if s.reviewed_at else None,
            "implemented_at": s.implemented_at.strftime("%b %d, %Y") if s.implemented_at else None
        })

    return result


@app.put("/api/suggestions/{suggestion_id}/forward")
def forward_suggestion(suggestion_id: int, data: dict, db: Session = Depends(get_db_local)):
    """Forward suggestion from coordinator to supervisors."""
    
    suggestion = db.query(Suggestion).filter(Suggestion.id == suggestion_id).first()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    if suggestion.status != "New":
        raise HTTPException(status_code=400, detail="Only new suggestions can be forwarded")

    suggestion.status = "Forwarded to Supervisor"
    suggestion.reviewed_at = datetime.now()
    suggestion.reviewed_by = data.get("forwarded_by")
    suggestion.response = data.get("response", "")
    db.commit()

    supervisors = db.query(User).filter(User.role == "supervisor").all()
    for supervisor in supervisors:
        notification = Notification(
            user_id=supervisor.id,
            title="Suggestion Forwarded for Review",
            message=f"A coordinator forwarded a suggestion in category: {suggestion.category}",
            type="suggestion"
        )
        db.add(notification)
    db.commit()

    if not suggestion.is_anonymous and suggestion.user_id:
        send_push_notification(
            suggestion.user_id,
            "ðŸ“¨ Suggestion Forwarded",
            "Your suggestion has been forwarded to a supervisor for review."
        )

    return {"message": "Suggestion forwarded to supervisor"}


@app.put("/api/suggestions/{suggestion_id}/review")
def review_suggestion(suggestion_id: int, data: dict, db: Session = Depends(get_db_local)):
    """Mark a suggestion as reviewed"""
    
    suggestion = db.query(Suggestion).filter(Suggestion.id == suggestion_id).first()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    
    suggestion.status = "Under Review"
    suggestion.reviewed_at = datetime.now()
    suggestion.reviewed_by = data.get('reviewed_by')
    suggestion.response = data.get('response', '')
    db.commit()
    
    # Notify the user if not anonymous
    if not suggestion.is_anonymous and suggestion.user_id:
        send_push_notification(
            suggestion.user_id,
            "ðŸ“ Suggestion Reviewed",
            f"Your suggestion '{suggestion.content[:50]}...' has been reviewed. {suggestion.response[:100] if suggestion.response else ''}"
        )
    
    return {"message": "Suggestion marked as reviewed"}


@app.put("/api/suggestions/{suggestion_id}/implement")
def implement_suggestion(suggestion_id: int, data: dict, db: Session = Depends(get_db_local)):
    """Mark a suggestion as implemented"""
    
    suggestion = db.query(Suggestion).filter(Suggestion.id == suggestion_id).first()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    
    suggestion.status = "Implemented"
    suggestion.implemented_at = datetime.now()
    db.commit()
    
    # Notify the user if not anonymous
    if not suggestion.is_anonymous and suggestion.user_id:
        send_push_notification(
            suggestion.user_id,
            "ðŸŽ‰ Suggestion Implemented!",
            f"Great news! Your suggestion '{suggestion.content[:50]}...' has been implemented."
        )
    
    return {"message": "Suggestion marked as implemented"}


@app.delete("/api/suggestions/{suggestion_id}")
def archive_suggestion(suggestion_id: int, db: Session = Depends(get_db_local)):
    """Archive a suggestion"""
    
    suggestion = db.query(Suggestion).filter(Suggestion.id == suggestion_id).first()
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    
    suggestion.status = "Archived"
    db.commit()
    
    return {"message": "Suggestion archived"}

# ==================== MESSAGING ENDPOINTS ====================

@app.post("/api/messages/send")
def send_message(data: dict, background_tasks: BackgroundTasks, db: Session = Depends(get_db_local)):
    """Send a message from one user to another"""
    
    sender_id = data.get('sender_id')
    receiver_id = data.get('receiver_id')
    content = data.get('content')
    subject = data.get('subject', 'Message')
    
    if not sender_id or not receiver_id or not content:
        raise HTTPException(status_code=400, detail="sender_id, receiver_id, and content are required")
    
    # Verify users exist
    sender = db.query(User).filter(User.id == sender_id, User.is_active == True).first()
    receiver = db.query(User).filter(User.id == receiver_id, User.is_active == True).first()
    
    if not sender:
        raise HTTPException(status_code=404, detail="Sender not found")
    if not receiver:
        raise HTTPException(status_code=404, detail="Receiver not found")
    
    # Create message
    message = Message(
        sender_id=sender_id,
        receiver_id=receiver_id,
        subject=subject,
        content=content,
        is_read=False,
        created_at=datetime.now()
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    
    # Send push notification to receiver
    background_tasks.add_task(
        send_push_notification,
        receiver_id,
        f"ðŸ’¬ New message from {sender.full_name}",
        content[:100] + ("..." if len(content) > 100 else "")
    )
    
    # Create notification in database
    notification = Notification(
        user_id=receiver_id,
        title=f"New Message from {sender.full_name}",
        message=content[:200],
        type="message",
        created_at=datetime.now()
    )
    db.add(notification)
    db.commit()
    
    return {
        "message": "Message sent successfully",
        "message_id": message.id,
        "created_at": message.created_at.isoformat()
    }


@app.get("/api/messages/conversation/{user1_id}/{user2_id}")
def get_conversation(user1_id: int, user2_id: int, limit: int = 100, offset: int = 0, db: Session = Depends(get_db_local)):
    """Get messages between two users"""
    
    messages = db.query(Message).filter(
        ((Message.sender_id == user1_id) & (Message.receiver_id == user2_id)) |
        ((Message.sender_id == user2_id) & (Message.receiver_id == user1_id))
    ).order_by(Message.created_at.desc()).offset(offset).limit(limit).all()
    
    # Reverse to get chronological order (oldest first)
    messages.reverse()
    
    result = []
    for msg in messages:
        result.append({
            "id": msg.id,
            "sender_id": msg.sender_id,
            "receiver_id": msg.receiver_id,
            "subject": msg.subject,
            "content": msg.content,
            "is_read": msg.is_read,
            "created_at": msg.created_at.isoformat(),
            "attachment_url": msg.attachment_url
        })
    
    return result


@app.get("/api/messages/conversations/{user_id}")
def get_user_conversations(user_id: int, db: Session = Depends(get_db_local)):
    """Get all conversations for a user (chat list)"""
    
    # Get all unique users that this user has messaged with
    sent_users = db.query(Message.receiver_id).filter(Message.sender_id == user_id).distinct().all()
    received_users = db.query(Message.sender_id).filter(Message.receiver_id == user_id).distinct().all()
    
    # Combine unique user IDs
    user_ids = set()
    for u in sent_users:
        user_ids.add(u[0])
    for u in received_users:
        user_ids.add(u[0])
    
    result = []
    for other_id in user_ids:
        # Get the other user
        other_user = db.query(User).filter(User.id == other_id).first()
        if not other_user:
            continue
        
        # Get last message between users
        last_message = db.query(Message).filter(
            ((Message.sender_id == user_id) & (Message.receiver_id == other_id)) |
            ((Message.sender_id == other_id) & (Message.receiver_id == user_id))
        ).order_by(Message.created_at.desc()).first()
        
        # Count unread messages for this user
        unread_count = db.query(Message).filter(
            Message.sender_id == other_id,
            Message.receiver_id == user_id,
            Message.is_read == False
        ).count()
        
        # Get profile info for student
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == other_id).first()
        
        result.append({
            "user_id": other_user.id,
            "user_name": other_user.full_name or other_user.username,
            "user_role": other_user.role,
            "student_id": profile.student_id if profile else None,
            "last_message": last_message.content[:100] if last_message else None,
            "last_message_time": last_message.created_at.isoformat() if last_message else None,
            "unread_count": unread_count
        })
    
    # Sort by last message time (most recent first)
    result.sort(key=lambda x: x.get("last_message_time") or "", reverse=True)
    
    return result


@app.post("/api/messages/mark-read/{user_id}/{other_user_id}")
def mark_messages_read(user_id: int, other_user_id: int, db: Session = Depends(get_db_local)):
    """Mark all messages from other_user to user as read"""
    
    messages = db.query(Message).filter(
        Message.sender_id == other_user_id,
        Message.receiver_id == user_id,
        Message.is_read == False
    ).all()
    
    for msg in messages:
        msg.is_read = True
        msg.read_at = datetime.now()
    
    db.commit()
    
    return {"message": "Messages marked as read", "count": len(messages)}


@app.get("/api/messages/unread/{user_id}")
def get_unread_count(user_id: int, db: Session = Depends(get_db_local)):
    """Get total unread message count for a user"""
    
    count = db.query(Message).filter(
        Message.receiver_id == user_id,
        Message.is_read == False
    ).count()
    
    return {"unread_count": count}


@app.delete("/api/messages/{message_id}")
def delete_message(message_id: int, user_id: int, db: Session = Depends(get_db_local)):
    """Delete a message (only sender or receiver can delete)"""
    
    message = db.query(Message).filter(Message.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    
    # Check if user is authorized to delete
    if message.sender_id != user_id and message.receiver_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this message")
    
    db.delete(message)
    db.commit()
    
    return {"message": "Message deleted successfully"}


@app.get("/api/messages/search/{user_id}")
def search_messages(user_id: int, q: str, db: Session = Depends(get_db_local)):
    """Search messages containing text"""
    
    messages = db.query(Message).filter(
        ((Message.sender_id == user_id) | (Message.receiver_id == user_id)),
        Message.content.ilike(f"%{q}%")
    ).order_by(Message.created_at.desc()).limit(50).all()
    
    result = []
    for msg in messages:
        other_user_id = msg.receiver_id if msg.sender_id == user_id else msg.sender_id
        other_user = db.query(User).filter(User.id == other_user_id).first()
        
        result.append({
            "id": msg.id,
            "content": msg.content,
            "sender_id": msg.sender_id,
            "receiver_id": msg.receiver_id,
            "created_at": msg.created_at.isoformat(),
            "other_user_name": other_user.full_name if other_user else "Unknown",
            "other_user_id": other_user_id
        })
    
    return result


@app.post("/api/messages/broadcast")
def broadcast_message(data: dict, background_tasks: BackgroundTasks, db: Session = Depends(get_db_local)):
    """Send broadcast message to all attachees (coordinator/supervisor only)"""
    
    sender_id = data.get('sender_id')
    subject = data.get('subject', 'Broadcast Message')
    content = data.get('content')
    role_filter = data.get('role_filter', 'attachee')
    
    if not sender_id or not content:
        raise HTTPException(status_code=400, detail="Sender ID and content required")
    
    # Verify sender is authorized
    sender = db.query(User).filter(User.id == sender_id).first()
    if not sender or sender.role not in ['coordinator', 'supervisor', 'it_manager']:
        raise HTTPException(status_code=403, detail="Not authorized to send broadcast messages")
    
    # Get recipients
    if role_filter == 'all':
        recipients = db.query(User).filter(User.is_active == True).all()
    elif role_filter == 'attachee':
        recipients = db.query(User).filter(User.role == 'attachee', User.is_active == True).all()
    elif role_filter == 'supervisor':
        recipients = db.query(User).filter(User.role == 'supervisor', User.is_active == True).all()
    elif role_filter == 'coordinator':
        recipients = db.query(User).filter(User.role == 'coordinator', User.is_active == True).all()
    else:
        recipients = db.query(User).filter(User.role == role_filter, User.is_active == True).all()
    
    # Send messages
    messages_sent = []
    for recipient in recipients:
        if recipient.id == sender_id:
            continue
        
        message = Message(
            sender_id=sender_id,
            receiver_id=recipient.id,
            subject=subject,
            content=content,
            is_read=False,
            created_at=datetime.now()
        )
        db.add(message)
        messages_sent.append(message.id)
        
        # Send push notification
        background_tasks.add_task(
            send_push_notification,
            recipient.id,
            f"ðŸ“¢ Broadcast: {subject}",
            content[:100] + ("..." if len(content) > 100 else "")
        )
    
    db.commit()
    
    return {
        "message": f"Broadcast sent to {len(messages_sent)} recipients",
        "recipient_count": len(messages_sent)
    }


@app.get("/api/messages/unread-conversations/{user_id}")
def get_unread_conversations(user_id: int, db: Session = Depends(get_db_local)):
    """Get all conversations with unread messages"""
    
    # Get all senders who have sent unread messages
    unread_senders = db.query(Message.sender_id).filter(
        Message.receiver_id == user_id,
        Message.is_read == False
    ).distinct().all()
    
    result = []
    for sender_id in unread_senders:
        other_user = db.query(User).filter(User.id == sender_id[0]).first()
        if not other_user:
            continue
        
        unread_count = db.query(Message).filter(
            Message.sender_id == sender_id[0],
            Message.receiver_id == user_id,
            Message.is_read == False
        ).count()
        
        latest = db.query(Message).filter(
            Message.sender_id == sender_id[0],
            Message.receiver_id == user_id
        ).order_by(Message.created_at.desc()).first()
        
        profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == sender_id[0]).first()
        
        result.append({
            "user_id": other_user.id,
            "user_name": other_user.full_name or other_user.username,
            "student_id": profile.student_id if profile else None,
            "user_role": other_user.role,
            "unread_count": unread_count,
            "latest_message": latest.content[:100] if latest else None,
            "latest_message_time": latest.created_at.isoformat() if latest else None
        })
    
    result.sort(key=lambda x: x["unread_count"], reverse=True)
    
    return result


@app.get("/api/payments/student/{student_id}")
def get_student_payments(
    student_id: int,
    db: Session = Depends(get_db_local)
):
    """Get all payments for a student"""
    
    student = db.query(User).filter(User.id == student_id, User.role == "attachee").first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    payments = db.query(Payment).filter(
        Payment.student_id == student_id
    ).order_by(Payment.payment_date.desc()).all()
    
    result = []
    for p in payments:
        result.append({
            "id": p.id,
            "payment_type": p.payment_type,
            "amount": float(p.amount),
            "payment_reference": p.payment_reference,
            "status": p.status,
            "payment_date": p.payment_date.isoformat() if p.payment_date else None,
            "notes": p.notes,
            "recorded_by": p.recorder.full_name if p.recorder else None
        })
    
    return result


@app.get("/api/payments/student/{student_id}/summary")
def get_payment_summary(
    student_id: int,
    db: Session = Depends(get_db_local)
):
    """Get payment summary by type"""
    
    student = db.query(User).filter(User.id == student_id, User.role == "attachee").first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    # Get contract for attachment fee
    contract = db.query(Contract).filter(
        Contract.attachee_id == student_id
    ).order_by(Contract.created_at.desc()).first()
    
    # Get all payments
    payments = db.query(Payment).filter(
        Payment.student_id == student_id,
        Payment.status == "completed"
    ).all()
    
    summary = {
        "application_fee": {"total": 120.00, "paid": 0, "due": 120.00},
        "attachment_fee": {"total": 0, "paid": 0, "due": 0},
        "assessment_fee": {"total": 0, "paid": 0, "due": 0},
        "completion_fee": {"total": 1550.00, "paid": 0, "due": 1550.00},
        "other": {"total": 0, "paid": 0, "due": 0}
    }
    
    # Set attachment fee based on contract mode
    if contract:
        mode = getattr(contract, 'mode', 'physical')
        summary["attachment_fee"]["total"] = 4950.00 if mode == 'online' else 2950.00
        summary["attachment_fee"]["paid"] = float(contract.amount_paid) if contract.amount_paid else 0
        summary["attachment_fee"]["due"] = summary["attachment_fee"]["total"] - summary["attachment_fee"]["paid"]
    
    # Check application fee from user record
    if student.transaction_verified:
        summary["application_fee"]["paid"] = float(student.amount_paid) if student.amount_paid else 120.00
        summary["application_fee"]["due"] = 0
    
    # Process payments table
    for p in payments:
        if p.payment_type == "application":
            summary["application_fee"]["paid"] = float(p.amount)
            summary["application_fee"]["due"] = max(0, summary["application_fee"]["total"] - summary["application_fee"]["paid"])
        elif p.payment_type == "attachment":
            summary["attachment_fee"]["paid"] += float(p.amount)
            summary["attachment_fee"]["due"] = max(0, summary["attachment_fee"]["total"] - summary["attachment_fee"]["paid"])
        elif p.payment_type == "assessment":
            summary["assessment_fee"]["total"] += float(p.amount)  # Assessment is custom, so total increases with each payment
            summary["assessment_fee"]["paid"] += float(p.amount)
        elif p.payment_type == "completion":
            summary["completion_fee"]["paid"] += float(p.amount)
            summary["completion_fee"]["due"] = max(0, summary["completion_fee"]["total"] - summary["completion_fee"]["paid"])
        elif p.payment_type == "other":
            summary["other"]["total"] += float(p.amount)
            summary["other"]["paid"] += float(p.amount)
    
    total_paid = sum([s["paid"] for s in summary.values()])
    total_due = sum([s["due"] for s in summary.values()])
    
    return {
        "summary": summary,
        "total_paid": total_paid,
        "total_due": total_due,
        "total_expected": total_paid + total_due
    }

# ==================== ACCOUNT AUTO-DISABLE & EXTENSION ENDPOINTS ====================

@app.get("/api/check-account-status/{user_id}")
def check_account_status(user_id: int, db: Session = Depends(get_db_local)):
    """Check if account is disabled due to unpaid fees (called on dashboard load)"""
    print(f"[check_account_status] called for user_id={user_id}")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        print(f"[check_account_status] user not found: {user_id}")
        raise HTTPException(status_code=404, detail="User not found")

    print(
        "[check_account_status] user state:",
        {
            "id": user.id,
            "is_active": user.is_active,
            "account_auto_disabled_at": user.account_auto_disabled_at,
            "contract_approved_at": user.contract_approved_at,
            "payment_deadline_days": getattr(user, "payment_deadline_days", None),
            "payment_deadline_extended_to": user.payment_deadline_extended_to,
        }
    )
    
    # If account is manually disabled by admin
    if not user.is_active and user.account_auto_disabled_at is None:
        print(f"[check_account_status] manual disable detected for user_id={user_id}")
        return {
            "is_active": False,
            "disabled_reason": "Account disabled by administrator",
            "disabled_at": None,
            "can_request_extension": False,
            "is_manual_disable": True
        }
    
    # Get contract details
    try:
        contract_details = get_contract_payment_details(user_id, db)
        print("[check_account_status] contract_details:", contract_details)
    except NameError:
        print("[check_account_status] get_contract_payment_details missing")
        contract_details = None
    
    if not contract_details:
        print(f"[check_account_status] no contract details for user_id={user_id}")
        return {"is_active": True, "has_contract": False}
    
    # Use the latest supervisor approval timestamp as the source of truth
    contract_approved_at = contract_details.get("supervisor_approved_at") or user.contract_approved_at
    if contract_approved_at and user.contract_approved_at != contract_approved_at:
        user.contract_approved_at = contract_approved_at
        db.commit()
    
    remaining_balance = contract_details["remaining_balance"]
    print(f"[check_account_status] remaining_balance={remaining_balance}")
    
    # If fully paid, ensure account is active
    if remaining_balance <= 0:
        if not user.is_active or user.account_auto_disabled_at:
            print(f"[check_account_status] fully paid; reactivating user_id={user_id}")
            user.is_active = True
            user.account_auto_disabled_at = None
            user.account_auto_disabled_reason = None
            db.commit()
        return {
            "is_active": True,
            "is_fully_paid": True,
            "remaining_balance": 0,
            "contract_approved_at": user.contract_approved_at.isoformat() if user.contract_approved_at else None,
            **contract_details
        }
    
    # Calculate deadline
    deadline_base = user.contract_approved_at or contract_approved_at
    deadline_date = user.payment_deadline_extended_to or (deadline_base + timedelta(days=user.payment_deadline_days)) if deadline_base else None
    print("deadline_date:", deadline_date)
    if not deadline_date:
        print(f"[check_account_status] no deadline date for user_id={user_id}; treating as active")
        return {"is_active": True, **contract_details}
    
    today = datetime.now()
    days_remaining = (deadline_date - today).days if deadline_date > today else 0
    days_overdue = abs(min(0, (deadline_date - today).days))
    print(
        "[check_account_status] deadline comparison:",
        {
            "today": today,
            "deadline_date": deadline_date,
            "days_remaining": days_remaining,
            "days_overdue": days_overdue,
        }
    )
    
    # Check if deadline has passed
    if today > deadline_date and remaining_balance > 0:
        # Auto-disable account if not already disabled
        if not user.account_auto_disabled_at:
            print(f"[check_account_status] auto-disabling user_id={user_id}")
            user.is_active = False
            user.account_auto_disabled_at = datetime.now()
            user.account_auto_disabled_reason = f"Payment deadline exceeded. KES {remaining_balance:,.2f} still pending after {user.payment_deadline_days} days."
            db.commit()
            
            # Create auto-disable request record
            auto_disable_request = DisableRequest(
                requested_by=user_id,
                target_user_id=user_id,
                target_role=user.role,
                reason=f"Auto-disable: Payment deadline exceeded after {user.payment_deadline_days} days. Balance: KES {remaining_balance:,.2f}",
                status="approved",
                disable_type="auto_disable",
                approved_at=datetime.now(),
                approved_by=user_id
            )
            db.add(auto_disable_request)
            db.commit()
        else:
            print(f"[check_account_status] already auto-disabled user_id={user_id}")
        
        return {
            "is_active": False,
            "disabled_reason": user.account_auto_disabled_reason,
            "disabled_at": user.account_auto_disabled_at.isoformat(),
            "days_overdue": days_overdue,
            "deadline_days": user.payment_deadline_days,
            "remaining_balance": remaining_balance,
            "has_extension": user.payment_deadline_extended_to is not None,
            "can_request_extension": True,
            **contract_details
        }
    
    # Account is active (within deadline)
    print(f"[check_account_status] user_id={user_id} remains active")
    return {
        "is_active": True,
        "remaining_balance": remaining_balance,
        "days_remaining": days_remaining,
        "deadline_date": deadline_date.isoformat(),
        "has_extension": user.payment_deadline_extended_to is not None,
        "can_request_extension": days_remaining <= 7,
        **contract_details
    }


@app.post("/api/request-account-extension/{user_id}")
def request_account_extension(
    user_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Attachee requests account extension from coordinator"""
    
    user = db.query(User).filter(User.id == user_id, User.role == "attachee").first()
    if not user:
        raise HTTPException(status_code=404, detail="Attachee not found")
    
    # Check if already disabled
    if not user.is_active or user.account_auto_disabled_at:
        raise HTTPException(status_code=400, detail="Account is already disabled. Please contact coordinator directly.")
    
    extension_days = data.get('extension_days', 14)
    reason = data.get('reason', 'Need more time to complete payment')
    
    # Get contract details
    contract_details = get_contract_payment_details(user_id, db)
    if not contract_details:
        raise HTTPException(status_code=400, detail="No approved contract found")
    
    # Create an extension request notification for coordinators
    coordinators = db.query(User).filter(User.role == "coordinator").all()
    
    for coord in coordinators:
        notification = Notification(
            user_id=coord.id,
            title="ðŸ“… Account Extension Request",
            message=f"Attachee {user.full_name} ({user.username}) requests {extension_days} days extension for payment. Remaining balance: KES {contract_details['remaining_balance']:,.2f}. Reason: {reason}",
            type="extension_request",
            is_read=False,
            created_at=datetime.now()
        )
        db.add(notification)
        
        # Send push notification
        background_tasks.add_task(
            send_push_notification,
            coord.id,
            "ðŸ“… Extension Request",
            f"{user.full_name} requests {extension_days} days payment extension"
        )
    
    # Also notify supervisor
    supervisor = db.query(User).filter(User.role == "supervisor").first()
    if supervisor:
        notification = Notification(
            user_id=supervisor.id,
            title="ðŸ“… Account Extension Request",
            message=f"Attachee {user.full_name} ({user.username}) requests {extension_days} days extension for payment. Remaining balance: KES {contract_details['remaining_balance']:,.2f}. Reason: {reason}",
            type="extension_request",
            is_read=False,
            created_at=datetime.now()
        )
        db.add(notification)
        
        background_tasks.add_task(
            send_push_notification,
            supervisor.id,
            "ðŸ“… Extension Request",
            f"{user.full_name} requests {extension_days} days payment extension"
        )
    
    # Create a disable request record for tracking
    extension_tracker = DisableRequest(
        requested_by=user_id,
        target_user_id=user_id,
        target_role="attachee",
        reason=f"Extension request: {extension_days} days. Reason: {reason}",
        status="pending",
        disable_type="extension_request",
        extension_days_requested=extension_days,
        is_extension_request=True,
        requested_at=datetime.now()
    )
    db.add(extension_tracker)
    db.commit()
    
    return {
        "message": "Extension request sent to coordinator",
        "request_id": extension_tracker.id,
        "extension_days": extension_days,
        "coordinator_notified": len(coordinators)
    }


@app.get("/api/coordinator/extension-requests")
def get_extension_requests(db: Session = Depends(get_db_local)):
    """Get all pending extension requests for coordinator"""
    
    extension_requests = db.query(DisableRequest).filter(
        DisableRequest.disable_type == "extension_request",
        DisableRequest.status == "pending",
        DisableRequest.is_extension_request == True
    ).order_by(DisableRequest.requested_at.desc()).all()
    
    result = []
    for req in extension_requests:
        student = db.query(User).filter(User.id == req.target_user_id).first()
        contract_details = get_contract_payment_details(req.target_user_id, db)
        deadline_date = None
        days_overdue = 0
        if student:
            deadline_date = student.payment_deadline_extended_to or (
                student.contract_approved_at + timedelta(days=student.payment_deadline_days)
                if student.contract_approved_at else None
            )
            if deadline_date:
                days_overdue = abs(min(0, (deadline_date - datetime.now()).days))
        
        result.append({
            "id": req.id,
            "student_id": req.target_user_id,
            "student_name": student.full_name if student else "Unknown",
            "student_username": student.username if student else "Unknown",
            "extension_days_requested": req.extension_days_requested,
            "reason": req.reason,
            "requested_at": req.requested_at.isoformat(),
            "remaining_balance": contract_details["remaining_balance"] if contract_details else 0,
            "contract_number": contract_details["contract_number"] if contract_details else "N/A"
        })

    return result


@app.get("/api/coordinator/auto-disabled-accounts")
def get_auto_disabled_accounts(db: Session = Depends(get_db_local)):
    """Get all auto-disabled attachees waiting for coordinator review."""

    disabled_requests = db.query(DisableRequest).filter(
        DisableRequest.disable_type == "auto_disable",
        DisableRequest.status == "approved"
    ).order_by(DisableRequest.requested_at.desc()).all()

    result = []
    for req in disabled_requests:
        student = db.query(User).filter(User.id == req.target_user_id).first()
        contract_details = get_contract_payment_details(req.target_user_id, db)
        deadline_date = None
        days_overdue = 0
        if student:
            deadline_date = student.payment_deadline_extended_to or (
                student.contract_approved_at + timedelta(days=student.payment_deadline_days)
                if student.contract_approved_at else None
            )
            if deadline_date:
                days_overdue = abs(min(0, (deadline_date - datetime.now()).days))

        result.append({
            "id": req.id,
            "student_id": student.username if student else "Unknown",
            "student_name": student.full_name if student else "Unknown",
            "student_username": student.username if student else "Unknown",
            "disabled_reason": student.account_auto_disabled_reason if student else req.reason,
            "disabled_at": student.account_auto_disabled_at.isoformat() if student and student.account_auto_disabled_at else req.requested_at.isoformat() if req.requested_at else None,
            "remaining_balance": contract_details["remaining_balance"] if contract_details else 0,
            "contract_number": contract_details["contract_number"] if contract_details else "N/A",
            "deadline_date": deadline_date.isoformat() if deadline_date else None,
            "days_overdue": days_overdue,
            "status": req.status,
            "reason": req.reason,
            "requested_at": req.requested_at.isoformat() if req.requested_at else None,
            "extension_days_requested": req.extension_days_requested or 0,
        })

    return result


@app.post("/api/coordinator/forward-extension/{request_id}")
def forward_extension_to_supervisor(
    request_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Coordinator forwards extension or auto-disable request to supervisor"""
    
    extension_request = db.query(DisableRequest).filter(
        DisableRequest.id == request_id,
        DisableRequest.disable_type.in_(["extension_request", "auto_disable"]),
        DisableRequest.status.in_(["pending", "approved"])
    ).first()
    
    if not extension_request:
        raise HTTPException(status_code=404, detail="Extension request not found")
    
    coordinator_notes = data.get('notes', '')
    
    # Update request status
    extension_request.status = "forwarded"
    db.commit()
    
    # Get student details
    student = db.query(User).filter(User.id == extension_request.target_user_id).first()
    contract_details = get_contract_payment_details(extension_request.target_user_id, db)
    forwarded_days = extension_request.extension_days_requested or 14
    
    # Notify supervisor
    supervisor = db.query(User).filter(User.role == "supervisor").first()
    if not supervisor:
        raise HTTPException(status_code=404, detail="No supervisor found")
    
    notification = Notification(
        user_id=supervisor.id,
        title="ðŸ“… Extension Request Forwarded",
        message=f"Coordinator forwards extension request from {student.full_name} for {forwarded_days} days.\nRemaining balance: KES {contract_details['remaining_balance']:,.2f}\nCoordinator notes: {coordinator_notes}",
        type="extension_request",
        is_read=False,
        created_at=datetime.now()
    )
    db.add(notification)
    
    background_tasks.add_task(
        send_push_notification,
        supervisor.id,
        "ðŸ“… Extension Request to Review",
        f"{student.full_name} requests {forwarded_days} days extension - forwarded by coordinator"
    )
    
    db.commit()
    
    return {
        "message": "Extension request forwarded to supervisor",
        "request_id": request_id,
        "supervisor_id": supervisor.id
    }


@app.get("/api/supervisor/extension-requests")
def get_supervisor_extension_requests(db: Session = Depends(get_db_local)):
    """Get all forwarded extension requests for supervisor"""
    
    extension_requests = db.query(DisableRequest).filter(
        DisableRequest.disable_type.in_(["extension_request", "auto_disable"]),
        DisableRequest.status == "forwarded"
    ).order_by(DisableRequest.requested_at.desc()).all()
    
    result = []
    for req in extension_requests:
        student = db.query(User).filter(User.id == req.target_user_id).first()
        contract_details = get_contract_payment_details(req.target_user_id, db)
        deadline_date = None
        days_overdue = 0
        if student:
            deadline_date = student.payment_deadline_extended_to or (
                student.contract_approved_at + timedelta(days=student.payment_deadline_days)
                if student.contract_approved_at else None
            )
            if deadline_date:
                days_overdue = abs(min(0, (deadline_date - datetime.now()).days))
        
        result.append({
            "id": req.id,
            "student_id": req.target_user_id,
            "student_name": student.full_name if student else "Unknown",
            "student_username": student.username if student else "Unknown",
            "extension_days_requested": req.extension_days_requested or 14,
            "reason": req.reason,
            "requested_at": req.requested_at.isoformat(),
            "remaining_balance": contract_details["remaining_balance"] if contract_details else 0,
            "contract_number": contract_details["contract_number"] if contract_details else "N/A",
            "disabled_reason": student.account_auto_disabled_reason if student else None,
            "disabled_at": student.account_auto_disabled_at.isoformat() if student and student.account_auto_disabled_at else None,
            "deadline_date": deadline_date.isoformat() if deadline_date else None,
            "days_overdue": days_overdue
        })
    
    return result


@app.post("/api/supervisor/grant-extension/{request_id}")
def grant_account_extension(
    request_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Supervisor grants extension to attachee"""
    
    extension_request = db.query(DisableRequest).filter(
        DisableRequest.id == request_id,
        DisableRequest.disable_type.in_(["extension_request", "auto_disable"]),
        DisableRequest.status == "forwarded"
    ).first()
    
    if not extension_request:
        raise HTTPException(status_code=404, detail="Extension request not found")
    
    supervisor_id = data.get('supervisor_id')
    extension_days = data.get('extension_days', extension_request.extension_days_requested)
    supervisor_notes = data.get('notes', '')
    
    # Verify supervisor exists
    supervisor = db.query(User).filter(User.id == supervisor_id, User.role == "supervisor").first()
    if not supervisor:
        raise HTTPException(status_code=404, detail="Supervisor not found")
    
    user = db.query(User).filter(User.id == extension_request.target_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Attachee not found")
    
    # Calculate new deadline
    if user.payment_deadline_extended_to:
        current_deadline = user.payment_deadline_extended_to
    elif user.contract_approved_at:
        current_deadline = user.contract_approved_at + timedelta(days=user.payment_deadline_days)
    else:
        raise HTTPException(status_code=400, detail="No contract approval date found")
    
    new_deadline = current_deadline + timedelta(days=extension_days)
    
    # Update user record
    user.payment_deadline_extended_to = new_deadline
    user.account_extension_days = extension_days
    user.account_extension_granted_at = datetime.now()
    user.account_extension_granted_by = supervisor_id
    
    # Re-activate account if it was disabled
    if not user.is_active or user.account_auto_disabled_at:
        user.is_active = True
        user.account_auto_disabled_at = None
        user.account_auto_disabled_reason = None
    
    db.commit()
    
    # Update the extension request
    extension_request.status = "approved"
    extension_request.approved_at = datetime.now()
    extension_request.approved_by = supervisor_id
    extension_request.extension_days_granted = extension_days
    db.commit()
    
    # Notify attachee
    background_tasks.add_task(
        send_push_notification,
        user.id,
        "âœ… Account Extension Granted",
        f"Your payment deadline has been extended by {extension_days} days. New deadline: {new_deadline.strftime('%Y-%m-%d')}"
    )
    
    notification = Notification(
        user_id=user.id,
        title="âœ… Extension Granted",
        message=f"Supervisor has granted {extension_days} days extension. New payment deadline: {new_deadline.strftime('%Y-%m-%d')}",
        type="extension_granted",
        is_read=False,
        created_at=datetime.now()
    )
    db.add(notification)
    
    # Notify coordinator
    coordinators = db.query(User).filter(User.role == "coordinator").all()
    for coord in coordinators:
        notification = Notification(
            user_id=coord.id,
            title="âœ… Extension Granted",
            message=f"Extension of {extension_days} days granted for {user.full_name}. New deadline: {new_deadline.strftime('%Y-%m-%d')}",
            type="extension_granted",
            is_read=False,
            created_at=datetime.now()
        )
        db.add(notification)
    
    db.commit()
    
    return {
        "message": f"Extension of {extension_days} days granted",
        "new_deadline": new_deadline.isoformat(),
        "user_id": user.id,
        "request_id": request_id
    }


@app.post("/api/supervisor/reject-extension/{request_id}")
def reject_extension_request(
    request_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_local)
):
    """Supervisor rejects extension request"""
    
    extension_request = db.query(DisableRequest).filter(
        DisableRequest.id == request_id,
        DisableRequest.disable_type.in_(["extension_request", "auto_disable"]),
        DisableRequest.status == "forwarded"
    ).first()
    
    if not extension_request:
        raise HTTPException(status_code=404, detail="Extension request not found")
    
    rejection_reason = data.get('rejection_reason', 'Request denied')
    
    extension_request.status = "rejected"
    extension_request.rejection_reason = rejection_reason
    extension_request.approved_at = datetime.now()
    db.commit()
    
    # Notify student
    student = db.query(User).filter(User.id == extension_request.target_user_id).first()
    if student:
        background_tasks.add_task(
            send_push_notification,
            student.id,
            "âŒ Extension Request Rejected",
            f"Your extension request has been rejected. Reason: {rejection_reason}"
        )
        
        notification = Notification(
            user_id=student.id,
            title="âŒ Extension Request Rejected",
            message=f"Your extension request has been rejected. Reason: {rejection_reason}",
            type="extension_rejected",
            is_read=False,
            created_at=datetime.now()
        )
        db.add(notification)
    
    db.commit()
    
    return {
        "message": "Extension request rejected",
        "request_id": request_id
    }


@app.post("/api/update-contract-approval/{contract_id}")
def update_contract_approval_date(
    contract_id: int,
    db: Session = Depends(get_db_local)
):
    """Update user's contract_approved_at when supervisor approves contract"""
    
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    
    user = db.query(User).filter(User.id == contract.attachee_id).first()
    if user and contract.supervisor_approved_at and not user.contract_approved_at:
        user.contract_approved_at = contract.supervisor_approved_at
        user.payment_deadline_days = 30
        db.commit()
        
        return {
            "message": "Contract approval date recorded",
            "contract_approved_at": user.contract_approved_at.isoformat(),
            "payment_deadline": (user.contract_approved_at + timedelta(days=user.payment_deadline_days)).isoformat()
        }
    
    return {"message": "No update needed"}

@app.post("/api/payments/record")
async def record_payment(
    request: FastAPIRequest, 
    background_tasks: BackgroundTasks, 
    db: Session = Depends(get_db_local)
):
    """Record a payment for a student"""
    try:
        data = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")
    
    student_id = data.get('student_id')
    payment_type = data.get('payment_type')
    amount = data.get('amount')
    payment_reference = data.get('payment_reference', '')
    notes = data.get('notes', '')
    
    if not student_id or not payment_type or amount is None:
        raise HTTPException(status_code=400, detail="Missing required fields: student_id, payment_type, amount")
    
    # Get student
    student = db.query(User).filter(User.id == student_id, User.role == "attachee").first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    profile = db.query(AttacheeProfile).filter(AttacheeProfile.user_id == student_id).first()
    contract_updated = False
    profile_updated = False
    
    # Handle different payment types
    if payment_type == "attachment":
        # Update contract attachment fee payment
        contract = db.query(Contract).filter(
            Contract.attachee_id == student_id
        ).order_by(Contract.created_at.desc()).first()
        
        if contract:
            current_paid = float(contract.amount_paid) if contract.amount_paid else 0
            contract.amount_paid = current_paid + amount
            contract.payment_reference = payment_reference
            contract.payment_date = datetime.now()
            contract_updated = True
            
            # Create payment record
            payment_record = Payment(
                student_id=student_id,
                payment_type="attachment",
                amount=amount,
                payment_reference=payment_reference,
                status="completed",
                notes=notes,
                payment_date=datetime.now()
            )
            db.add(payment_record)
            print(f"âœ… Attachment payment recorded: KES {amount:,.2f} for contract {contract.contract_number}")
    
    elif payment_type == "assessment":
        # Update assessment fee in profile
        if profile:
            current_assessment = float(profile.assessment_paid) if profile.assessment_paid else 0
            profile.assessment_paid = current_assessment + amount
            profile.assessment_payment_reference = payment_reference
            profile.assessment_payment_date = datetime.now()
            profile_updated = True
            
            # Also update contract if exists
            contract = db.query(Contract).filter(
                Contract.attachee_id == student_id
            ).order_by(Contract.created_at.desc()).first()
            
            if contract:
                current_assessment = float(contract.assessment_paid) if hasattr(contract, 'assessment_paid') and contract.assessment_paid else 0
                contract.assessment_paid = current_assessment + amount
                contract.assessment_payment_reference = payment_reference
                contract.assessment_payment_date = datetime.now()
            
            payment_record = Payment(
                student_id=student_id,
                payment_type="assessment",
                amount=amount,
                payment_reference=payment_reference,
                status="completed",
                notes=notes,
                payment_date=datetime.now()
            )
            db.add(payment_record)
            print(f"âœ… Assessment payment recorded: KES {amount:,.2f} for student {student.username}")
    
    elif payment_type == "completion":
        # Update completion fee in contract
        contract = db.query(Contract).filter(
            Contract.attachee_id == student_id
        ).order_by(Contract.created_at.desc()).first()
        
        if contract:
            current_completion = float(contract.completion_paid) if hasattr(contract, 'completion_paid') and contract.completion_paid else 0
            contract.completion_paid = current_completion + amount
            contract.completion_payment_reference = payment_reference
            contract.completion_payment_date = datetime.now()
            contract_updated = True
            
            payment_record = Payment(
                student_id=student_id,
                payment_type="completion",
                amount=amount,
                payment_reference=payment_reference,
                status="completed",
                notes=notes,
                payment_date=datetime.now()
            )
            db.add(payment_record)
            print(f"âœ… Completion payment recorded: KES {amount:,.2f} for contract {contract.contract_number}")
    
    else:  # "other"
        payment_record = Payment(
            student_id=student_id,
            payment_type="other",
            amount=amount,
            payment_reference=payment_reference,
            status="completed",
            notes=notes,
            payment_date=datetime.now()
        )
        db.add(payment_record)
        print(f"âœ… Other payment recorded: KES {amount:,.2f} for student {student.username}")
    
    db.commit()
    
    # Send notification to student
    background_tasks.add_task(
        send_push_notification,
        student_id,
        "ðŸ’° Payment Recorded",
        f"KES {amount:,.2f} {payment_type} payment has been recorded. Reference: {payment_reference}"
    )
    
    # Create notification for student
    notification = Notification(
        user_id=student_id,
        title="Payment Recorded",
        message=f"KES {amount:,.2f} {payment_type} payment has been recorded successfully.",
        type="payment",
        is_read=False
    )
    db.add(notification)
    
    # Notify coordinators
    coordinators = db.query(User).filter(User.role == "coordinator").all()
    for coord in coordinators:
        coord_notification = Notification(
            user_id=coord.id,
            title="Payment Recorded",
            message=f"Payment of KES {amount:,.2f} recorded for {student.full_name} ({payment_type})",
            type="payment",
            is_read=False
        )
        db.add(coord_notification)
    
    db.commit()
    
    return {
        "success": True,
        "message": "Payment recorded successfully",
        "contract_updated": contract_updated,
        "profile_updated": profile_updated,
        "amount": amount,
        "payment_type": payment_type
    }
# ==================== REGINA (BUSINESS DEVELOPMENT) API ====================

from pydantic import BaseModel
from typing import Optional as _Opt
from datetime import date as _date


class ReginaCampaignEntryIn(BaseModel):
    campaign: str
    platform: str
    group_name: str
    posted: bool = False
    reached: int = 0
    expected_positive_replies: int = 0
    converted: int = 0
    entry_date: _Opt[str] = None


def _require_regina_reader(request: FastAPIRequest, db: Session):
    user = get_current_user(request, db)
    if user.role not in {"business_development", "supervisor"}:
        raise HTTPException(status_code=403, detail="Forbidden for role " + user.role)
    return user


def _require_regina_owner(request: FastAPIRequest, db: Session):
    user = get_current_user(request, db)
    if user.role != "business_development":
        raise HTTPException(status_code=403, detail="Only business_development can write")
    return user


def _serialize_regina_entry(e: ReginaCampaignEntry) -> dict:
    return {
        "id": e.id, "user_id": e.user_id,
        "campaign": e.campaign, "platform": e.platform,
        "group_name": e.group_name, "posted": bool(e.posted),
        "reached": int(e.reached or 0),
        "expected_positive_replies": int(e.expected_positive_replies or 0),
        "converted": int(e.converted or 0),
        "entry_date": e.entry_date.isoformat() if e.entry_date else None,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "updated_at": e.updated_at.isoformat() if e.updated_at else None,
    }


@app.get("/api/regina/campaign-report")
def regina_list_campaigns(request: FastAPIRequest, db: Session = Depends(get_db_local)):
    viewer = _require_regina_reader(request, db)
    q = db.query(ReginaCampaignEntry)
    if viewer.role == "business_development":
        q = q.filter(ReginaCampaignEntry.user_id == viewer.id)
    rows = q.order_by(ReginaCampaignEntry.entry_date.desc(),
                      ReginaCampaignEntry.id.desc()).all()
    return [_serialize_regina_entry(r) for r in rows]


@app.get("/api/regina/campaign-report/{entry_id}")
def regina_get_campaign(entry_id: int, request: FastAPIRequest,
                        db: Session = Depends(get_db_local)):
    viewer = _require_regina_reader(request, db)
    e = db.query(ReginaCampaignEntry).filter(ReginaCampaignEntry.id == entry_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Not found")
    if viewer.role == "business_development" and e.user_id != viewer.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return _serialize_regina_entry(e)


@app.post("/api/regina/campaign-report")
def regina_create_campaign(payload: ReginaCampaignEntryIn,
                           request: FastAPIRequest,
                           db: Session = Depends(get_db_local)):
    owner = _require_regina_owner(request, db)
    entry_date = _date.fromisoformat(payload.entry_date) if payload.entry_date else _date.today()
    e = ReginaCampaignEntry(
        user_id=owner.id,
        campaign=payload.campaign, platform=payload.platform,
        group_name=payload.group_name, posted=payload.posted,
        reached=payload.reached,
        expected_positive_replies=payload.expected_positive_replies,
        converted=payload.converted, entry_date=entry_date,
    )
    db.add(e); db.commit(); db.refresh(e)
    return _serialize_regina_entry(e)


@app.put("/api/regina/campaign-report/{entry_id}")
def regina_update_campaign(entry_id: int, payload: ReginaCampaignEntryIn,
                           request: FastAPIRequest,
                           db: Session = Depends(get_db_local)):
    owner = _require_regina_owner(request, db)
    e = db.query(ReginaCampaignEntry).filter(ReginaCampaignEntry.id == entry_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Not found")
    if e.user_id != owner.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    e.campaign = payload.campaign; e.platform = payload.platform
    e.group_name = payload.group_name; e.posted = payload.posted
    e.reached = payload.reached
    e.expected_positive_replies = payload.expected_positive_replies
    e.converted = payload.converted
    if payload.entry_date:
        e.entry_date = _date.fromisoformat(payload.entry_date)
    db.commit(); db.refresh(e)
    return _serialize_regina_entry(e)


@app.delete("/api/regina/campaign-report/{entry_id}")
def regina_delete_campaign(entry_id: int, request: FastAPIRequest,
                           db: Session = Depends(get_db_local)):
    owner = _require_regina_owner(request, db)
    e = db.query(ReginaCampaignEntry).filter(ReginaCampaignEntry.id == entry_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Not found")
    if e.user_id != owner.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    db.delete(e); db.commit()
    return {"ok": True}


@app.get("/api/regina/summary")
def regina_summary(request: FastAPIRequest, db: Session = Depends(get_db_local)):
    viewer = _require_regina_reader(request, db)
    q = db.query(ReginaCampaignEntry)
    if viewer.role == "business_development":
        q = q.filter(ReginaCampaignEntry.user_id == viewer.id)
    rows = q.all()
    total_groups = len(rows)
    groups_posted = sum(1 for r in rows if r.posted)
    total_reached = sum(int(r.reached or 0) for r in rows)
    expected = sum(int(r.expected_positive_replies or 0) for r in rows)
    converted = sum(int(r.converted or 0) for r in rows)
    rate = (converted / total_reached * 100) if total_reached else 0.0
    return {
        "total_groups": total_groups, "groups_posted": groups_posted,
        "total_reached": total_reached, "expected_positive_replies": expected,
        "total_converted": converted, "conversion_rate": round(rate, 2),
    }


@app.get("/api/regina/notifications")
def regina_notifications(request: FastAPIRequest, db: Session = Depends(get_db_local)):
    viewer = get_current_user(request, db)
    if viewer.role != "business_development":
        raise HTTPException(status_code=403, detail="Forbidden")
    rows = (db.query(Notification)
            .filter(Notification.user_id == viewer.id)
            .order_by(Notification.created_at.desc())
            .limit(50).all())
    return [{
        "id": n.id, "title": n.title, "message": n.message, "type": n.type,
        "is_read": n.is_read, "action_url": n.action_url,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    } for n in rows]

@app.post("/api/sync/upload")
async def sync_upload(payload: dict, request: FastAPIRequest, db: Session = Depends(get_db_local)):
    ops = payload.get("operations", [])
    synced, failed = [], []
    for op in ops:
        t = op.get("type"); data = op.get("data") or {}
        lid = op.get("local_id")
        try:
            if t == "regina_campaign_create":
                owner = db.query(User).filter(User.id == op.get("user_id")).first()
                if not owner or owner.role != "business_development":
                    failed.append({"local_id": lid, "reason": "invalid user"}); continue
                entry_date = _date.fromisoformat(data["entry_date"]) if data.get("entry_date") else _date.today()
                db.add(ReginaCampaignEntry(
                    user_id=owner.id, campaign=data["campaign"], platform=data["platform"],
                    group_name=data["group_name"], posted=bool(data.get("posted")),
                    reached=int(data.get("reached") or 0),
                    expected_positive_replies=int(data.get("expected_positive_replies") or 0),
                    converted=int(data.get("converted") or 0), entry_date=entry_date,
                ))
            elif t == "regina_campaign_update":
                e = db.query(ReginaCampaignEntry).filter(ReginaCampaignEntry.id == data.get("id")).first()
                if not e: failed.append({"local_id": lid, "reason": "not found"}); continue
                for k in ("campaign", "platform", "group_name"):
                    if k in data: setattr(e, k, data[k])
                for k in ("posted", "reached", "expected_positive_replies", "converted"):
                    if k in data: setattr(e, k, data[k] if k == "posted" else int(data[k] or 0))
                if data.get("entry_date"): e.entry_date = _date.fromisoformat(data["entry_date"])
            elif t == "regina_campaign_delete":
                e = db.query(ReginaCampaignEntry).filter(ReginaCampaignEntry.id == data.get("id")).first()
                if e: db.delete(e)
                        elif t == "regina_letter_status":
                letter = db.query(ReginaPartnershipLetter).filter(
                    ReginaPartnershipLetter.id == data.get("id")).first()
                if letter and data.get("status") in {"pending", "approved", "sent"}:
                    letter.status = data["status"]
                    letter.sent_at = datetime.now() if data["status"] == "sent" else letter.sent_at
            elif t == "regina_todo_toggle":
                todo = db.query(ReginaTodo).filter(ReginaTodo.id == data.get("id")).first()
                if todo:
                    todo.done = bool(data.get("done"))
                    todo.done_at = datetime.now() if todo.done else None
            elif t == "regina_todo_create":
                entry_date = _date.fromisoformat(data["entry_date"]) if data.get("entry_date") else _date.today()
                db.add(ReginaTodo(
                    user_id=op.get("user_id") or 0, entry_date=entry_date,
                    block=data.get("block", "morning"),
                    time_label=data.get("time_label", ""),
                    section_title=data.get("section_title", ""),
                    task_text=data.get("task_text", ""),
                    done=False, position=int(data.get("position") or 0),
                ))
            elif t == "regina_todo_delete":
                todo = db.query(ReginaTodo).filter(ReginaTodo.id == data.get("id")).first()
                if todo: db.delete(todo)
            else:
                failed.append({"local_id": lid, "reason": f"unknown type {t}"}); continue
            synced.append(lid)
        except Exception as ex:
            failed.append({"local_id": lid, "reason": str(ex)})
    db.commit()
    return {"synced": len(synced), "failed": len(failed),
            "synced_ids": synced, "failed_operations": failed}

# ==================== REGINA — PARTNERSHIP LETTERS ====================

from fastapi import UploadFile, File, Form
from pathlib import Path as _Path
import os as _os
import shutil as _shutil


REGINA_LETTERS_DIR = Config.UPLOAD_DIR / "regina" / "partnership_letters"
REGINA_LETTERS_DIR.mkdir(parents=True, exist_ok=True)

_ALLOWED_LETTER_EXT = {".pdf", ".doc", ".docx"}


def _serialize_regina_letter(l: ReginaPartnershipLetter) -> dict:
    return {
        "id": l.id,
        "user_id": l.user_id,
        "title": l.title,
        "recipient": l.recipient,
        "status": l.status,
        "file_name": l.file_name,
        "mime_type": l.mime_type,
        "notes": l.notes,
        "sent_at": l.sent_at.isoformat() if l.sent_at else None,
        "created_at": l.created_at.isoformat() if l.created_at else None,
        "updated_at": l.updated_at.isoformat() if l.updated_at else None,
        "download_url": f"/api/regina/partnership-letters/{l.id}/download",
    }


@app.get("/api/regina/partnership-letters")
def regina_list_letters(
    request: FastAPIRequest,
    db: Session = Depends(get_db_local),
):
    owner = _require_regina_owner(request, db)
    rows = (
        db.query(ReginaPartnershipLetter)
        .filter(ReginaPartnershipLetter.user_id == owner.id)
        .order_by(ReginaPartnershipLetter.created_at.desc())
        .all()
    )
    return [_serialize_regina_letter(r) for r in rows]


@app.post("/api/regina/partnership-letters")
async def regina_upload_letter(
    request: FastAPIRequest,
    title: str = Form(...),
    recipient: str = Form(""),
    status: str = Form("pending"),
    notes: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db_local),
):
    owner = _require_regina_owner(request, db)

    ext = _Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_LETTER_EXT:
        raise HTTPException(status_code=400, detail="Only PDF, DOC, or DOCX files are allowed")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = f"regina_letter_{owner.id}_{timestamp}{ext}"
    file_path = REGINA_LETTERS_DIR / safe_name

    with open(file_path, "wb") as buffer:
        _shutil.copyfileobj(file.file, buffer)

    letter = ReginaPartnershipLetter(
        user_id=owner.id,
        title=title.strip() or (file.filename or "Untitled"),
        recipient=recipient.strip() or None,
        status=status if status in {"pending", "approved", "sent"} else "pending",
        file_path=str(file_path),
        file_name=file.filename or safe_name,
        mime_type=file.content_type or "application/octet-stream",
        notes=notes.strip() or None,
        sent_at=datetime.now() if status == "sent" else None,
    )
    db.add(letter)
    db.commit()
    db.refresh(letter)
    return _serialize_regina_letter(letter)


@app.put("/api/regina/partnership-letters/{letter_id}")
def regina_update_letter(
    letter_id: int,
    payload: dict,
    request: FastAPIRequest,
    db: Session = Depends(get_db_local),
):
    owner = _require_regina_owner(request, db)
    letter = (
        db.query(ReginaPartnershipLetter)
        .filter(ReginaPartnershipLetter.id == letter_id,
                ReginaPartnershipLetter.user_id == owner.id)
        .first()
    )
    if not letter:
        raise HTTPException(status_code=404, detail="Letter not found")

    if "title" in payload and payload["title"]:
        letter.title = str(payload["title"]).strip()
    if "recipient" in payload:
        letter.recipient = (str(payload["recipient"]).strip() or None)
    if "notes" in payload:
        letter.notes = (str(payload["notes"]).strip() or None)
    if "status" in payload and payload["status"] in {"pending", "approved", "sent"}:
        letter.status = payload["status"]
        letter.sent_at = datetime.now() if payload["status"] == "sent" else letter.sent_at
    db.commit()
    db.refresh(letter)
    return _serialize_regina_letter(letter)


@app.delete("/api/regina/partnership-letters/{letter_id}")
def regina_delete_letter(
    letter_id: int,
    request: FastAPIRequest,
    db: Session = Depends(get_db_local),
):
    owner = _require_regina_owner(request, db)
    letter = (
        db.query(ReginaPartnershipLetter)
        .filter(ReginaPartnershipLetter.id == letter_id,
                ReginaPartnershipLetter.user_id == owner.id)
        .first()
    )
    if not letter:
        raise HTTPException(status_code=404, detail="Letter not found")
    try:
        if _os.path.exists(letter.file_path):
            _os.remove(letter.file_path)
    except Exception:
        pass
    db.delete(letter)
    db.commit()
    return {"ok": True}


@app.get("/api/regina/partnership-letters/{letter_id}/download")
def regina_download_letter(
    letter_id: int,
    request: FastAPIRequest,
    db: Session = Depends(get_db_local),
):
    viewer = _require_regina_reader(request, db)
    letter = db.query(ReginaPartnershipLetter).filter(
        ReginaPartnershipLetter.id == letter_id).first()
    if not letter:
        raise HTTPException(status_code=404, detail="Letter not found")
    if viewer.role == "business_development" and letter.user_id != viewer.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not _os.path.exists(letter.file_path):
        raise HTTPException(status_code=404, detail="File missing on disk")
    return FileResponse(letter.file_path, media_type=letter.mime_type,
                        filename=letter.file_name)


# ==================== REGINA — TO-DO LIST ====================

def _seed_default_todo_template(user_id: int, entry_date, db: Session):
    default = [
        ("morning", "7:15 - 8:15am",
         "Cleaning and Supervision and Office Preparation",
         "Clean and supervise my area of inspection and prepare my working area for the day's task."),
        ("morning", "8:30am - 1:00pm",
         "Kick-starting the day. Share 4 industrial attachment partnership letters and market the Airbnbs and attachment",
         "Prepare and share Industrial Attachment Partnership letters with potential institutions"),
        ("morning", "8:30am - 1:00pm",
         "Kick-starting the day. Share 4 industrial attachment partnership letters and market the Airbnbs and attachment",
         "Airbnb and Attachment campaign in social groups e.g Facebook, Instagram and Tiktok."),
        ("afternoon", "2:00 - 3:30pm",
         "Review the day's work, prepare the next day's work and share my daily matrix report",
         "Review the day's activities and ensure completion of tasks."),
        ("afternoon", "2:00 - 3:30pm",
         "Review the day's work, prepare the next day's work and share my daily matrix report",
         "Prepare and share my Daily Matrix Report"),
    ]
    for idx, (block, time_label, section, task) in enumerate(default):
        db.add(ReginaTodo(
            user_id=user_id, entry_date=entry_date, block=block,
            time_label=time_label, section_title=section, task_text=task,
            done=False, position=idx,
        ))
    db.commit()


def _serialize_todo(t: ReginaTodo) -> dict:
    return {
        "id": t.id,
        "entry_date": t.entry_date.isoformat() if t.entry_date else None,
        "block": t.block,
        "time_label": t.time_label,
        "section_title": t.section_title,
        "task_text": t.task_text,
        "done": bool(t.done),
        "done_at": t.done_at.isoformat() if t.done_at else None,
        "position": t.position,
    }


@app.get("/api/regina/todos")
def regina_list_todos(
    request: FastAPIRequest,
    entry_date: Optional[str] = None,
    db: Session = Depends(get_db_local),
):
    owner = _require_regina_owner(request, db)
    target = _date.fromisoformat(entry_date) if entry_date else _date.today()

    rows = (
        db.query(ReginaTodo)
        .filter(ReginaTodo.user_id == owner.id, ReginaTodo.entry_date == target)
        .order_by(ReginaTodo.position.asc(), ReginaTodo.id.asc())
        .all()
    )
    if not rows:
        _seed_default_todo_template(owner.id, target, db)
        rows = (
            db.query(ReginaTodo)
            .filter(ReginaTodo.user_id == owner.id, ReginaTodo.entry_date == target)
            .order_by(ReginaTodo.position.asc(), ReginaTodo.id.asc())
            .all()
        )
    return {"entry_date": target.isoformat(),
            "items": [_serialize_todo(r) for r in rows]}


@app.post("/api/regina/todos")
def regina_create_todo(
    payload: dict,
    request: FastAPIRequest,
    db: Session = Depends(get_db_local),
):
    owner = _require_regina_owner(request, db)
    entry_date = _date.fromisoformat(payload["entry_date"]) if payload.get("entry_date") else _date.today()
    max_pos = (db.query(ReginaTodo)
               .filter(ReginaTodo.user_id == owner.id, ReginaTodo.entry_date == entry_date)
               .count())
    todo = ReginaTodo(
        user_id=owner.id, entry_date=entry_date,
        block=payload.get("block", "morning"),
        time_label=payload.get("time_label", ""),
        section_title=payload.get("section_title", ""),
        task_text=(payload.get("task_text") or "").strip(),
        done=False, position=max_pos,
    )
    if not todo.task_text:
        raise HTTPException(status_code=400, detail="task_text is required")
    db.add(todo); db.commit(); db.refresh(todo)
    return _serialize_todo(todo)


@app.put("/api/regina/todos/{todo_id}")
def regina_update_todo(
    todo_id: int,
    payload: dict,
    request: FastAPIRequest,
    db: Session = Depends(get_db_local),
):
    owner = _require_regina_owner(request, db)
    todo = (db.query(ReginaTodo)
            .filter(ReginaTodo.id == todo_id, ReginaTodo.user_id == owner.id)
            .first())
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    for field in ("block", "time_label", "section_title", "task_text", "position"):
        if field in payload:
            setattr(todo, field, payload[field])
    if "done" in payload:
        todo.done = bool(payload["done"])
        todo.done_at = datetime.now() if todo.done else None
    db.commit(); db.refresh(todo)
    return _serialize_todo(todo)


@app.delete("/api/regina/todos/{todo_id}")
def regina_delete_todo(
    todo_id: int,
    request: FastAPIRequest,
    db: Session = Depends(get_db_local),
):
    owner = _require_regina_owner(request, db)
    todo = (db.query(ReginaTodo)
            .filter(ReginaTodo.id == todo_id, ReginaTodo.user_id == owner.id)
            .first())
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    db.delete(todo); db.commit()
    return {"ok": True}


# ==================== REGINA — DAILY MATRIX + REPORTS ====================

def _report_row_for_day(user_id: int, target: _date, db: Session):
    rows = (
        db.query(ReginaCampaignEntry)
        .filter(ReginaCampaignEntry.user_id == user_id,
                ReginaCampaignEntry.entry_date == target)
        .all()
    )
    reached = sum(int(r.reached or 0) for r in rows)
    expected = sum(int(r.expected_positive_replies or 0) for r in rows)
    converted = sum(int(r.converted or 0) for r in rows)
    posted = sum(1 for r in rows if r.posted)
    rate = (converted / reached * 100) if reached else 0.0

    todos = (
        db.query(ReginaTodo)
        .filter(ReginaTodo.user_id == user_id, ReginaTodo.entry_date == target)
        .all()
    )
    total_tasks = len(todos)
    done_tasks = sum(1 for t in todos if t.done)

    return {
        "date": target.isoformat(),
        "groups": len(rows),
        "groups_posted": posted,
        "reached": reached,
        "expected_replies": expected,
        "converted": converted,
        "conversion_rate": round(rate, 2),
        "tasks_total": total_tasks,
        "tasks_done": done_tasks,
        "entries": [
            {"campaign": r.campaign, "platform": r.platform,
             "group_name": r.group_name, "posted": bool(r.posted),
             "reached": int(r.reached or 0),
             "expected_positive_replies": int(r.expected_positive_replies or 0),
             "converted": int(r.converted or 0)}
            for r in rows
        ],
        "todos": [
            {"block": t.block, "time_label": t.time_label,
             "section_title": t.section_title, "task_text": t.task_text,
             "done": bool(t.done)}
            for t in todos
        ],
    }


def _aggregate_report(period_rows):
    total = {"days": len(period_rows), "groups": 0, "groups_posted": 0,
             "reached": 0, "expected_replies": 0, "converted": 0,
             "tasks_total": 0, "tasks_done": 0}
    for r in period_rows:
        for k in ("groups", "groups_posted", "reached",
                  "expected_replies", "converted", "tasks_total", "tasks_done"):
            total[k] += r[k]
    total["conversion_rate"] = round(
        (total["converted"] / total["reached"] * 100) if total["reached"] else 0.0, 2)
    return total


@app.get("/api/regina/daily-matrix")
def regina_daily_matrix(
    request: FastAPIRequest,
    entry_date: Optional[str] = None,
    db: Session = Depends(get_db_local),
):
    """One day's matrix snapshot, incl. entries + todos + totals."""
    owner = _require_regina_owner(request, db)
    target = _date.fromisoformat(entry_date) if entry_date else _date.today()
    return _report_row_for_day(owner.id, target, db)


@app.get("/api/regina/reports/preview")
def regina_report_preview(
    request: FastAPIRequest,
    report_type: str,             # daily | weekly | monthly | range
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db_local),
):
    """Aggregated preview used by the Daily Matrix 'Generate Report' panel."""
    owner = _require_regina_owner(request, db)
    today = _date.today()

    if report_type == "daily":
        start = _date.fromisoformat(start_date) if start_date else today
        end = start
    elif report_type == "weekly":
        start = _date.fromisoformat(start_date) if start_date else (today - timedelta(days=today.weekday()))
        end = start + timedelta(days=6)
    elif report_type == "monthly":
        anchor = _date.fromisoformat(start_date) if start_date else today
        start = anchor.replace(day=1)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end = start.replace(month=start.month + 1, day=1) - timedelta(days=1)
    elif report_type == "range":
        if not start_date or not end_date:
            raise HTTPException(status_code=400, detail="start_date and end_date required")
        start = _date.fromisoformat(start_date)
        end = _date.fromisoformat(end_date)
    else:
        raise HTTPException(status_code=400, detail="Invalid report_type")

    if end < start:
        raise HTTPException(status_code=400, detail="end_date must be on/after start_date")

    daily = []
    cursor = start
    while cursor <= end:
        daily.append(_report_row_for_day(owner.id, cursor, db))
        cursor += timedelta(days=1)

    return {
        "report_type": report_type,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "daily": daily,
        "totals": _aggregate_report(daily),
    }


if __name__ == "__main__":
    import uvicorn
    import os
    
    # Use same ports as app.py
    HTTP_PORT = 8002
    HTTPS_PORT = 8443
    
    # Check if certificate files exist using resource path
    cert_path = get_resource_path("cert.pem")
    key_path = get_resource_path("key.pem")
    
    print(f"ðŸ“ Looking for certificates:")
    print(f"   cert.pem: {cert_path} (exists: {os.path.exists(cert_path)})")
    print(f"   key.pem: {key_path} (exists: {os.path.exists(key_path)})")
    
    if os.path.exists(cert_path) and os.path.exists(key_path):
        print("=" * 60)
        print("ðŸ”’ Starting server with HTTPS (Camera will work)")
        print("=" * 60)
        print(f"   HTTP (Desktop): http://localhost:{HTTP_PORT}")
        print(f"   HTTPS (Web): https://{Config.get_local_ip()}:{HTTPS_PORT}")
        print("   âš ï¸  Browser will show security warning - click 'Advanced' â†’ 'Proceed'")
        print("=" * 60)
        
        uvicorn.run(
            app, 
            host="0.0.0.0", 
            port=HTTPS_PORT,
            ssl_keyfile=key_path,
            ssl_certfile=cert_path
        )
    else:
        print("=" * 60)
        print("âš ï¸  Starting server with HTTP (Camera may not work)")
        print(f"   HTTP (Desktop): http://localhost:{HTTP_PORT}")
        print("   Run 'python generate_cert.py' to enable HTTPS for web interface")
        print("=" * 60)
        
        uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT)

