import streamlit as st
from prompts import build_prompt, build_image_prompt
from utils import call_ai_model, call_vision_model, call_vision_model_multi, process_html_result, track_usage
import base64
from io import BytesIO
from PIL import Image
import requests
import json
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# API base URL
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

# Set page configuration
st.set_page_config(
    page_title="Counterfeit Risk Checker", 
    layout="centered",
    initial_sidebar_state="collapsed"
)

# Custom CSS including auth components
st.markdown("""
<style>
    .risk-low {
        color: #28a745;
        font-weight: bold;
        padding: 5px 10px;
        border-radius: 5px;
        background-color: rgba(40, 167, 69, 0.1);
    }
    .risk-medium {
        color: #ffc107;
        font-weight: bold;
        padding: 5px 10px;
        border-radius: 5px;
        background-color: rgba(255, 193, 7, 0.1);
    }
    .risk-high {
        color: #dc3545;
        font-weight: bold;
        padding: 5px 10px;
        border-radius: 5px;
        background-color: rgba(220, 53, 69, 0.1);
    }
    .confidence-high {
        color: #28a745;
        font-weight: bold;
    }
    .confidence-medium {
        color: #ffc107;
        font-weight: bold;
    }
    .confidence-low {
        color: #dc3545;
        font-weight: bold;
    }
    .flag-red {
        color: #dc3545;
        padding: 3px 8px;
        border-radius: 3px;
        background-color: rgba(220, 53, 69, 0.1);
        margin-bottom: 5px;
        display: inline-block;
    }
    .flag-green {
        color: #28a745;
        padding: 3px 8px;
        border-radius: 3px;
        background-color: rgba(40, 167, 69, 0.1);
        margin-bottom: 5px;
        display: inline-block;
    }
    .condition-header {
        font-weight: 600;
        margin-top: 1rem;
        color: #6c757d;
    }
    .condition-rating {
        font-weight: bold;
    }
    .condition-notes {
        font-style: italic;
        color: #6c757d;
    }
    .age-header {
        font-weight: 600;
        margin-top: 1rem;
        color: #6c757d;
    }
    .age-assessment {
        font-style: italic;
        color: #6c757d;
    }
    .main-header {
        font-size: 2rem;
        font-weight: 600;
        margin-bottom: 1rem;
    }
    .explanation {
        font-style: italic;
        margin: 1rem 0;
    }
    .tips-header, .visual-header, .flags-header {
        font-weight: 600;
        margin-top: 1rem;
    }
    .platform-header {
        font-weight: 600;
        margin-top: 1rem;
    }
    .tab-content {
        padding: 10px 0;
    }
    .disclaimer {
        font-size: 0.8rem;
        color: #6c757d;
        font-style: italic;
        margin-top: 8px;
    }
    
    /* Auth related styles */
    .auth-container {
        background-color: #f8f9fa;
        padding: 20px;
        border-radius: 10px;
        margin-bottom: 20px;
        border: 1px solid #dee2e6;
    }
    .auth-header {
        font-size: 1.2rem;
        font-weight: 600;
        margin-bottom: 15px;
    }
    .auth-tabs {
        display: flex;
        margin-bottom: 15px;
    }
    .auth-tab {
        padding: 8px 16px;
        cursor: pointer;
        border-bottom: 2px solid transparent;
        transition: all 0.3s;
    }
    .auth-tab.active {
        border-bottom: 2px solid #1f77b4;
        font-weight: 600;
    }
    .auth-message {
        padding: 8px 12px;
        border-radius: 4px;
        margin-bottom: 10px;
    }
    .auth-error {
        background-color: rgba(220, 53, 69, 0.1);
        color: #dc3545;
    }
    .auth-success {
        background-color: rgba(40, 167, 69, 0.1);
        color: #28a745;
    }
    .usage-count {
        display: inline-block;
        background-color: #f8f9fa;
        padding: 4px 10px;
        border-radius: 15px;
        font-size: 0.8rem;
        color: #6c757d;
        margin-left: 10px;
        border: 1px solid #dee2e6;
    }
    .login-wall {
        background-color: rgba(0, 0, 0, 0.03);
        padding: 20px;
        border-radius: 8px;
        text-align: center;
        margin: 20px 0;
        border: 1px solid #dee2e6;
    }
    .user-info {
        display: flex;
        align-items: center;
        justify-content: space-between;
        background-color: #f8f9fa;
        padding: 8px 15px;
        border-radius: 20px;
        margin: 10px 0;
        border: 1px solid #dee2e6;
    }
    .user-name {
        font-weight: 600;
        margin-right: 10px;
    }
    .logout-btn {
        background-color: transparent;
        border: none;
        color: #6c757d;
        cursor: pointer;
        font-size: 0.9rem;
        padding: 2px 8px;
    }
    .logout-btn:hover {
        color: #dc3545;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state for authentication
if 'auth_status' not in st.session_state:
    st.session_state.auth_status = {
        'authenticated': False,
        'user': None,
        'anonymous_uses_remaining': 5,
        'anonymous_uses_limit': 5
    }

if 'show_login_wall' not in st.session_state:
    st.session_state.show_login_wall = False

if 'auth_tab' not in st.session_state:
    st.session_state.auth_tab = 'login'

if 'auth_message' not in st.session_state:
    st.session_state.auth_message = None

# Function to check authentication status
def check_auth_status():
    try:
        response = requests.get(
            f"{API_BASE_URL}/auth/check",
            cookies=st.session_state.get('cookies', {}),
        )
        
        if response.status_code == 200:
            st.session_state.auth_status = response.json()
            return st.session_state.auth_status
        else:
            st.error("Failed to check authentication status")
            return {
                'authenticated': False,
                'user': None,
                'anonymous_uses_remaining': 5,
                'anonymous_uses_limit': 5
            }
    except Exception as e:
        st.error(f"Error checking authentication: {str(e)}")
        return {
            'authenticated': False,
            'user': None,
            'anonymous_uses_remaining': 5,
            'anonymous_uses_limit': 5
        }

# Function to track usage
def track_usage():
    try:
        response = requests.post(
            f"{API_BASE_URL}/auth/track-usage",
            cookies=st.session_state.get('cookies', {}),
        )
        
        if response.status_code == 200:
            result = response.json()
            
            # Update auth status after tracking
            check_auth_status()
            
            # If usage is limited for anonymous user, show login wall
            if not result.get('authenticated') and result.get('usage_limited'):
                st.session_state.show_login_wall = True
                
            return result
        else:
            return {
                'authenticated': False,
                'usage_limited': False,
                'usage_count': 0,
                'uses_remaining': 5
            }
    except Exception as e:
        st.error(f"Error tracking usage: {str(e)}")
        return {
            'authenticated': False,
            'usage_limited': False,
            'usage_count': 0,
            'uses_remaining': 5
        }

# Function to handle login
def handle_login(email, password):
    try:
        data = {
            'username': email,  # OAuth2 form expects 'username'
            'password': password,
        }
        
        response = requests.post(
            f"{API_BASE_URL}/auth/login",
            data=data,
            allow_redirects=False,
        )
        
        # Get cookies from response
        cookies = response.cookies.get_dict()
        
        if response.status_code == 200:
            # Store cookies in session state
            st.session_state.cookies = cookies
            
            # Update auth status
            check_auth_status()
            
            # Set success message
            st.session_state.auth_message = {
                'type': 'success',
                'text': 'Login successful!'
            }
            
            # Hide login wall if it was showing
            st.session_state.show_login_wall = False
            
            # Rerun to update UI
            st.rerun()
        else:
            error_detail = "Invalid credentials"
            if response.headers.get('content-type') == 'application/json':
                try:
                    error_detail = response.json().get('detail', error_detail)
                except:
                    pass
                    
            st.session_state.auth_message = {
                'type': 'error',
                'text': error_detail
            }
    except Exception as e:
        st.session_state.auth_message = {
            'type': 'error',
            'text': f"Error during login: {str(e)}"
        }

# Function to handle registration
def handle_register(name, email, password):
    try:
        data = {
            'name': name,
            'email': email,
            'password': password,
        }
        
        response = requests.post(
            f"{API_BASE_URL}/auth/register",
            json=data,
            allow_redirects=False,
        )
        
        # Get cookies from response
        cookies = response.cookies.get_dict()
        
        if response.status_code == 201:
            # Store cookies in session state
            st.session_state.cookies = cookies
            
            # Update auth status
            check_auth_status()
            
            # Set success message
            st.session_state.auth_message = {
                'type': 'success',
                'text': 'Registration successful!'
            }
            
            # Hide login wall if it was showing
            st.session_state.show_login_wall = False
            
            # Rerun to update UI
            st.rerun()
        else:
            error_detail = "Registration failed"
            if response.headers.get('content-type') == 'application/json':
                try:
                    error_detail = response.json().get('detail', error_detail)
                except:
                    pass
                    
            st.session_state.auth_message = {
                'type': 'error',
                'text': error_detail
            }
    except Exception as e:
        st.session_state.auth_message = {
            'type': 'error',
            'text': f"Error during registration: {str(e)}"
        }

# Function to handle logout
def handle_logout():
    try:
        response = requests.post(
            f"{API_BASE_URL}/auth/logout",
            cookies=st.session_state.get('cookies', {}),
        )
        
        # Clear cookies and auth status
        st.session_state.cookies = {}
        st.session_state.auth_status = {
            'authenticated': False,
            'user': None,
            'anonymous_uses_remaining': 5,
            'anonymous_uses_limit': 5
        }
        
        # Set success message
        st.session_state.auth_message = {
            'type': 'success',
            'text': 'Logged out successfully'
        }
        
        # Rerun to update UI
        st.rerun()
    except Exception as e:
        st.session_state.auth_message = {
            'type': 'error',
            'text': f"Error during logout: {str(e)}"
        }