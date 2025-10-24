import os
from flask import Flask, render_template, redirect, flash, request, url_for, abort, send_file
from dotenv import load_dotenv
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from sqlalchemy import select,func
from sqlalchemy.exc import IntegrityError
from flask_wtf.csrf import CSRFProtect
from flask_wtf import FlaskForm
# from sqlalchemy import func
# from datetime import date
from decorators import require_role
from pdf_gen import create_report_pdf

# from io import BytesIO
# from weasyprint import HTML
from ai_service import generate_health_report 


from database import db
from models import (
    User, Worker, HealthcareFacility, HealthRecord, ActivityLog, Vaccination, MedicalVisit,
    UserRoleEnum, GenderEnum, OccupationEnum, FrequencyEnum, DietTypeEnum,
    PPEUsageEnum, PhysicalStrainEnum, AccommodationEnum, SanitationEnum
)
from forms import (
    SignUpForm, LoginForm, WorkerDetailsForm, HealthcareFacilityForm,
    HealthRecordForm, ActivityLogForm, VaccinationForm, MedicalVisitForm, AdminAddUserForm
)

# App Initialization 

# An empty form is used for the logout button which doesn't need any fields.
class EmptyForm(FlaskForm):
    pass

load_dotenv()
app = Flask(__name__)
csrf = CSRFProtect(app)

# ✅ Direct MySQL configuration — no env vars
db_user = "root"
db_pass = "xJSLXYgysLURGNpHLTdKZAhURIWboNom"
db_host = "centerbeam.proxy.rlwy.net"
db_port = "56784"
db_name = "railway"

# ✅ Construct SQLAlchemy URI
app.config["SQLALCHEMY_DATABASE_URI"] = (
    f"mysql+pymysql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
)

# ✅ SQLAlchemy and Flask settings
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = "super-secret-key"

# ✅ Initialize database
db.init_app(app)

# ✅ Optional: verify DB connectivity at startup
try:
    with app.app_context():
        conn = db.engine.connect()
        print("✅ Database connection successful")
        conn.close()
except Exception as e:
    print("❌ Database connection failed:", e)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# This makes the 'logout_form' available in all templates
@app.context_processor
def inject_forms():
    return dict(logout_form=EmptyForm())


#  AUTHENTICATION ROUTES 

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = SignUpForm()
    if form.validate_on_submit():
        user = User(username=form.username.data.strip(), email=form.email.data.strip().lower())
        user.set_password(form.password.data)
        try:
            db.session.add(user)
            db.session.commit()
            flash("Account created successfully! Please log in.", "success")
            return redirect(url_for("login"))
        except IntegrityError:
            db.session.rollback()
            flash("That username or email is already taken.", "error")
    elif request.method == 'POST':
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{field.replace('_', ' ').title()}: {error}", 'error')
    return render_template("signup.html.j2", form=form)

@app.route("/login", methods=["POST", "GET"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data.strip()).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember_me.data)
            next_page = request.args.get('next')
            flash(f"Welcome back, {user.username}!", "success")
            return redirect(next_page or url_for('dashboard'))
        else:
            flash("Invalid username or password. Please try again.", "error")
    elif request.method == 'POST':
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{field.replace('_', ' ').title()}: {error}", 'error')
    return render_template('login.html.j2', form=form)

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out successfully.", "info")
    return redirect(url_for("home"))

@app.route("/admin_dashboard", methods=["GET", "POST"])
@require_role(["admin"])
def admin_dashboard():
    form = AdminAddUserForm()
    facility_form = HealthcareFacilityForm()
    if form.validate_on_submit():  
        user = User(username=form.username.data.strip(),email=form.email.data.strip().lower(),role=form.role.data)
        user.set_password(form.password.data)
        try:
            db.session.add(user)
            db.session.commit()
            flash("User created successfully!", "success")
        except IntegrityError:
            db.session.rollback()
            flash("That username or email is already taken.", "error")
        
        # redirecting after a successful or failed POST to prevent resubmission
        return redirect(url_for('admin_dashboard'))
    search_query = request.args.get('search', '').strip()
    search_results = []
    if search_query:
        search_results = User.query.filter(User.username.ilike(f"%{search_query}%")).all()
        if not search_results:
            flash(f"No users found for '{search_query}'.", "warning")
    # This handles all GET requests and POST requests with invalid data
    no_of_users = db.session.scalar(select(func.count()).select_from(User))
    total_facilities = db.session.scalar(select(func.count()).select_from(HealthcareFacility))
    if facility_form.submit.data and facility_form.validate():
        new_facility = HealthcareFacility(
            registered_by_user_id=current_user.id if current_user.is_authenticated else 1,
            facility_name=facility_form.facility_name.data.strip(),
            facility_type=facility_form.facility_type.data.strip(),
            facility_license_number=facility_form.facility_license_number.data.strip(),
            facility_address=facility_form.facility_address.data.strip(),
            facility_city=facility_form.facility_city.data.strip()
        )
        try:
            db.session.add(new_facility)
            db.session.commit()
            flash("New healthcare facility added successfully!", "success")
        except IntegrityError:
            db.session.rollback()
            flash("A facility with this license number already exists.", "danger")
        return redirect(url_for("admin_dashboard"))
    return render_template("admin_dashboard.html.j2",total_users=no_of_users,
                           total_hospitals=total_facilities,
                           form=form,
                           facility_form=facility_form,
                           search_results=search_results,
                           search_query=search_query)

# CORE APP ROUTES 
@app.route("/")
def home():
    return render_template('index.html.j2') 

@app.route("/dashboard")
@login_required
def dashboard():
    # passing worker objetc to the template
    worker = current_user.worker

    if current_user.role == UserRoleEnum.ADMIN:
        return redirect(url_for('admin_dashboard'))
    
    return render_template('dashboard.html.j2', worker=worker)

@app.route("/tos")
def tos():
    return render_template('tos.html')

# Worker Profile Routes 

@app.route("/create-profile", methods=["GET", "POST"])
@login_required
def worker_details():
    if current_user.worker:
        flash("You have already created your profile. You can edit it instead.", "info")
        return redirect(url_for('dashboard'))

    form = WorkerDetailsForm()
    if form.validate_on_submit():
        
        worker = Worker(
            user_id=current_user.id,
            first_name=form.first_name.data,
            last_name=form.last_name.data,
            age=form.age.data,
            phone=form.phone.data,
            home_state=form.home_state.data,
            gender=GenderEnum(form.gender.data),
            # Occupational
            occupation=OccupationEnum(form.occupation.data),
            work_hours_per_day=form.work_hours_per_day.data,
            physical_strain=PhysicalStrainEnum(form.physical_strain.data),
            ppe_usage=PPEUsageEnum(form.ppe_usage.data),
            # Lifestyle
            smoking_habit=FrequencyEnum(form.smoking_habit.data),
            alcohol_consumption=FrequencyEnum(form.alcohol_consumption.data),
            diet_type=DietTypeEnum(form.diet_type.data),
            meals_per_day=form.meals_per_day.data,
            junk_food_frequency=FrequencyEnum(form.junk_food_frequency.data),
            sleep_hours_per_night=form.sleep_hours_per_night.data,
            # Living Conditions
            accommodation_type=AccommodationEnum(form.accommodation_type.data),
            sanitation_quality=SanitationEnum(form.sanitation_quality.data),
            access_to_clean_water=form.access_to_clean_water.data,
            # Mental Health
            stress_level=form.stress_level.data,
            has_social_support=form.has_social_support.data
        )
        db.session.add(worker)
        db.session.commit()
        flash("Your profile has been created successfully!", "success")
        return redirect(url_for('dashboard'))
    elif request.method == 'POST':
        flash("Please correct the errors below.", "error")
        
    return render_template('worker_details.html.j2', form=form, page_title="Create Your Profile")

@app.route("/edit-profile", methods=["GET", "POST"])
@login_required
def edit_details():
    worker = current_user.worker
    if not worker:
        flash("You need to create your profile first.", "warning")
        return redirect(url_for('worker_details'))

    form = WorkerDetailsForm(obj=worker)
    if form.validate_on_submit():
        # pre filling the details
        form.populate_obj(worker)
        
        # Manually update all the Enum fields
        worker.gender = GenderEnum(form.gender.data)
        worker.occupation = OccupationEnum(form.occupation.data)
        worker.physical_strain = PhysicalStrainEnum(form.physical_strain.data)
        worker.ppe_usage = PPEUsageEnum(form.ppe_usage.data)
        worker.smoking_habit = FrequencyEnum(form.smoking_habit.data)
        worker.alcohol_consumption = FrequencyEnum(form.alcohol_consumption.data)
        worker.diet_type = DietTypeEnum(form.diet_type.data)
        worker.junk_food_frequency = FrequencyEnum(form.junk_food_frequency.data)
        worker.accommodation_type = AccommodationEnum(form.accommodation_type.data)
        worker.sanitation_quality = SanitationEnum(form.sanitation_quality.data)

        db.session.commit()
        flash("Your profile has been updated successfully!", "success")
        return redirect(url_for('dashboard'))
    
    elif request.method == 'POST':
        flash("Please correct the errors below.", "error")

    return render_template('worker_details.html.j2', form=form, page_title="Edit Your Profile")



@app.route("/add-health-record", methods=["GET", "POST"])
@login_required
def add_health_record():
    worker = current_user.worker
    if not worker:
        flash("Please create your profile before adding health records.", "warning")
        return redirect(url_for('worker_details'))
    
    form = HealthRecordForm()
    if form.validate_on_submit():
        health_record = HealthRecord(
            worker_id=worker.id,
            record_date= form.record_date.data,
            height_cm=form.height_cm.data,
            weight_kg=form.weight_kg.data,
            blood_pressure_systolic=form.blood_pressure_systolic.data,
            blood_pressure_diastolic=form.blood_pressure_diastolic.data,
            chronic_diseases = form.chronic_diseases.data
        )
        
        db.session.add(health_record)
        db.session.commit()
        flash("Health record added successfully!", "success")
        return redirect(url_for('dashboard'))

    return render_template('health_Record.html.j2', form=form, page_title="Add Health Record")

@app.route("/log-activity", methods=["GET", "POST"])
@login_required
def log_activity():
    if not current_user.worker:
        flash("Please create your profile first.", "warning")
        return redirect(url_for('worker_details'))
        
    form = ActivityLogForm()
    if form.validate_on_submit():
        activity = ActivityLog(
            worker_id=current_user.worker.id,
            activity_type=form.activity_type.data,
            duration_minutes=form.duration_minutes.data,
            notes=form.notes.data
        )
        db.session.add(activity)
        db.session.commit()
        flash("Activity logged successfully!", "success")
        return redirect(url_for('dashboard'))

    return render_template('log_activity.html.j2', form=form)

@app.route("/add-vaccination", methods=["GET", "POST"])
@login_required
def add_vaccination():
    if not current_user.worker:
        flash("Please create your profile first.", "warning")
        return redirect(url_for('worker_details'))

    form = VaccinationForm()
    if form.validate_on_submit():
        vaccination = Vaccination(
            worker_id=current_user.worker.id,
            vaccine_name=form.vaccine_name.data,
            dose_number=form.dose_number.data,
            date_administered=form.date_administered.data
        )
        db.session.add(vaccination)
        db.session.commit()
        flash("Vaccination record added!", "success")
        return redirect(url_for('dashboard'))

    return render_template('add_vaccination.html.j2', form=form)

# Routes for Health Officials 

@app.route("/register-facility", methods=["GET","POST"])
@login_required
def register_facility():
    # Restricting access
    if current_user.role != UserRoleEnum.HEALTH_OFFICIAL:
        flash("You do not have permission to register a facility.", "error")
        return redirect(url_for('dashboard'))

    form = HealthcareFacilityForm()
    if form.validate_on_submit():
        facility = HealthcareFacility(
            registered_by_user_id=current_user.id,
            facility_name = form.facility_name.data,
            facility_type = form.facility_type.data,
            facility_license_number = form.facility_license_number.data,
            facility_address = form.facility_address.data,
            facility_city = form.facility_city.data
        )
        db.session.add(facility)
        db.session.commit()
        flash("Healthcare facility registered successfully!", "success")
        return redirect(url_for('dashboard'))
        
    return render_template('healthcare_facility.html.j2', form=form, page_title="Register Facility")

@app.route("/worker/<int:worker_id>/add-medical-visit", methods=["GET", "POST"])
@login_required
def add_medical_visit(worker_id):
    # Restricting access
    if current_user.role != UserRoleEnum.HEALTH_OFFICIAL:
        abort(403) # Forbidden access

    worker = Worker.query.get_or_404(worker_id)
    form = MedicalVisitForm()

    if form.validate_on_submit():
        visit = MedicalVisit(
            worker_id=worker.id,
            facility_id=form.facility_id.data,
            doctor_name=form.doctor_name.data,
            visit_date=form.visit_date.data,
            diagnosis=form.diagnosis.data,
            report_id=form.report_id.data
        )
        db.session.add(visit)
        db.session.commit()
        flash(f"Medical visit for {worker.first_name} has been recorded.", "success")
        return redirect(url_for('dashboard')) 

    return render_template('add_medical_visit.html.j2', form=form, worker=worker)


@app.route("/generate-report")
@login_required
def generate_report():
    worker = current_user.worker
    if not worker:
        flash("You must create a worker profile before generating a report.", "warning")
        return redirect(url_for('worker_details'))

    
    # calling Ollama Llama3
    report_content = generate_health_report(worker)
    report_content = report_content.replace("**","")
    
    if "Error:" in report_content:
        flash(report_content, "error")
        return redirect(url_for('dashboard'))


    worker_name = f"{worker.first_name} {worker.last_name or ''}".strip()
    pdf_stream = create_report_pdf(report_content, worker_name)
    
    # 3. Send file to user 
    return send_file(
        pdf_stream,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'Health_Report_{worker_name.replace(" ", "_")}.pdf'
    )
# Main Execution 

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)