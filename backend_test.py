import requests
import sys
import json
from datetime import datetime
import time

class ABCMusicLibraryTester:
    def __init__(self, base_url="https://musicsheets-1.preview.emergentagent.com/api"):
        self.base_url = base_url
        self.token = None
        self.user_id = None
        self.tests_run = 0
        self.tests_passed = 0
        self.test_users = {}  # Store different role users
        
    def log_test(self, name, success, details=""):
        """Log test results"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            print(f"✅ {name} - PASSED {details}")
        else:
            print(f"❌ {name} - FAILED {details}")
        return success

    def make_request(self, method, endpoint, data=None, files=None, expected_status=200):
        """Make HTTP request with proper headers"""
        url = f"{self.base_url}/{endpoint}"
        headers = {'Content-Type': 'application/json'}
        
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
            
        if files:
            # Remove content-type for file uploads
            headers.pop('Content-Type', None)
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers)
            elif method == 'POST':
                if files:
                    response = requests.post(url, data=data, files=files, headers=headers)
                else:
                    response = requests.post(url, json=data, headers=headers)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=headers)
            elif method == 'DELETE':
                response = requests.delete(url, headers=headers)
            
            success = response.status_code == expected_status
            response_data = {}
            
            try:
                response_data = response.json()
            except:
                response_data = {"text": response.text}
                
            return success, response_data, response.status_code
            
        except Exception as e:
            return False, {"error": str(e)}, 0

    def test_root_endpoint(self):
        """Test root API endpoint"""
        success, data, status = self.make_request('GET', '', expected_status=200)
        return self.log_test("Root Endpoint", success, f"Status: {status}")

    def test_user_registration(self, role="student"):
        """Test user registration"""
        timestamp = int(time.time())
        test_data = {
            "email": f"test_{role}_{timestamp}@example.com",
            "password": "TestPass123!",
            "full_name": f"Test {role.title()} User",
            "role": role
        }
        
        success, data, status = self.make_request('POST', 'auth/register', test_data, expected_status=200)
        
        if success and 'access_token' in data:
            self.test_users[role] = {
                'token': data['access_token'],
                'user': data['user'],
                'credentials': test_data
            }
            
        return self.log_test(f"User Registration ({role})", success, f"Status: {status}")

    def test_user_login(self, role="student"):
        """Test user login"""
        if role not in self.test_users:
            return self.log_test(f"User Login ({role})", False, "No test user created")
            
        credentials = self.test_users[role]['credentials']
        login_data = {
            "email": credentials['email'],
            "password": credentials['password']
        }
        
        success, data, status = self.make_request('POST', 'auth/login', login_data, expected_status=200)
        
        if success and 'access_token' in data:
            self.token = data['access_token']
            self.user_id = data['user']['id']
            
        return self.log_test(f"User Login ({role})", success, f"Status: {status}")

    def test_get_current_user(self):
        """Test getting current user info"""
        success, data, status = self.make_request('GET', 'auth/me', expected_status=200)
        return self.log_test("Get Current User", success, f"Status: {status}")

    def test_update_profile(self):
        """Test profile update"""
        update_data = {
            "full_name": "Updated Test User",
            "avatar_url": "https://example.com/avatar.jpg"
        }
        
        success, data, status = self.make_request('PUT', 'users/profile', update_data, expected_status=200)
        return self.log_test("Update Profile", success, f"Status: {status}")

    def test_create_sheet_music(self):
        """Test creating sheet music (requires teacher/admin role)"""
        sheet_data = {
            "title": "Test Sheet Music",
            "composer": "Test Composer",
            "genre": "classical",
            "difficulty_level": "beginner",
            "description": "A test sheet music piece",
            "tags": ["test", "classical", "beginner"]
        }
        
        success, data, status = self.make_request('POST', 'sheet-music', sheet_data, expected_status=200)
        
        if success and 'id' in data:
            self.sheet_music_id = data['id']
            
        return self.log_test("Create Sheet Music", success, f"Status: {status}")

    def test_get_sheet_music(self):
        """Test getting sheet music list"""
        success, data, status = self.make_request('GET', 'sheet-music', expected_status=200)
        return self.log_test("Get Sheet Music List", success, f"Status: {status}, Count: {len(data) if isinstance(data, list) else 0}")

    def test_get_sheet_music_with_filters(self):
        """Test getting sheet music with filters"""
        success, data, status = self.make_request('GET', 'sheet-music?genre=classical&difficulty=beginner', expected_status=200)
        return self.log_test("Get Sheet Music with Filters", success, f"Status: {status}")

    def test_create_lesson(self):
        """Test creating lesson (requires teacher/admin role)"""
        lesson_data = {
            "title": "Test Music Theory Lesson",
            "description": "A comprehensive lesson on basic music theory",
            "content": "<h1>Music Theory Basics</h1><p>This lesson covers fundamental concepts...</p>",
            "category": "theory",
            "difficulty_level": "beginner",
            "exercises": [
                {
                    "question": "What is a major scale?",
                    "type": "multiple_choice",
                    "options": ["A scale with 7 notes", "A scale with 5 notes", "A chord progression"],
                    "correct_answer": 0
                }
            ]
        }
        
        success, data, status = self.make_request('POST', 'lessons', lesson_data, expected_status=200)
        
        if success and 'id' in data:
            self.lesson_id = data['id']
            
        return self.log_test("Create Lesson", success, f"Status: {status}")

    def test_get_lessons(self):
        """Test getting lessons list"""
        success, data, status = self.make_request('GET', 'lessons', expected_status=200)
        return self.log_test("Get Lessons List", success, f"Status: {status}, Count: {len(data) if isinstance(data, list) else 0}")

    def test_get_lessons_with_filters(self):
        """Test getting lessons with filters"""
        success, data, status = self.make_request('GET', 'lessons?category=theory&difficulty=beginner', expected_status=200)
        return self.log_test("Get Lessons with Filters", success, f"Status: {status}")

    def test_dashboard_stats(self):
        """Test dashboard stats endpoint"""
        success, data, status = self.make_request('GET', 'dashboard/stats', expected_status=200)
        
        if success:
            has_required_fields = all(key in data for key in ['user', 'stats', 'recent_sheet_music', 'recent_lessons'])
            success = success and has_required_fields
            
        return self.log_test("Dashboard Stats", success, f"Status: {status}")

    def test_update_lesson_progress(self):
        """Test updating lesson progress"""
        if not hasattr(self, 'lesson_id'):
            return self.log_test("Update Lesson Progress", False, "No lesson ID available")
            
        progress_data = {
            "completed": True,
            "score": 85
        }
        
        success, data, status = self.make_request('POST', f'progress/{self.lesson_id}?completed=true&score=85', expected_status=200)
        return self.log_test("Update Lesson Progress", success, f"Status: {status}")

    def test_get_user_progress(self):
        """Test getting user progress"""
        success, data, status = self.make_request('GET', 'progress', expected_status=200)
        return self.log_test("Get User Progress", success, f"Status: {status}")

    def test_file_upload_simulation(self):
        """Test file upload endpoint (simulated)"""
        # Create a simple test file content
        test_file_content = b"Test PDF content"
        files = {'file': ('test.pdf', test_file_content, 'application/pdf')}
        form_data = {'file_type': 'pdf'}
        
        success, data, status = self.make_request('POST', 'files/upload', data=form_data, files=files, expected_status=200)
        return self.log_test("File Upload (Simulated)", success, f"Status: {status}")

    def test_unauthorized_access(self):
        """Test unauthorized access"""
        # Temporarily remove token
        original_token = self.token
        self.token = None
        
        success, data, status = self.make_request('GET', 'auth/me', expected_status=401)
        
        # Restore token
        self.token = original_token
        
        return self.log_test("Unauthorized Access", success, f"Status: {status}")

    def test_role_based_permissions(self):
        """Test role-based permissions"""
        # Test student trying to create sheet music (should fail)
        if 'student' in self.test_users:
            student_token = self.test_users['student']['token']
            original_token = self.token
            self.token = student_token
            
            sheet_data = {
                "title": "Unauthorized Sheet Music",
                "composer": "Test",
                "genre": "classical",
                "difficulty_level": "beginner"
            }
            
            success, data, status = self.make_request('POST', 'sheet-music', sheet_data, expected_status=403)
            
            # Restore original token
            self.token = original_token
            
            return self.log_test("Role-based Permissions", success, f"Status: {status}")
        
        return self.log_test("Role-based Permissions", False, "No student user available")

    def run_comprehensive_tests(self):
        """Run all tests in sequence"""
        print("🚀 Starting ABC Music Library API Tests")
        print("=" * 50)
        
        # Basic connectivity
        self.test_root_endpoint()
        
        # Test user registration for different roles
        self.test_user_registration("student")
        self.test_user_registration("teacher")
        self.test_user_registration("admin")
        
        # Test login with student user
        self.test_user_login("student")
        
        # Test authenticated endpoints with student
        self.test_get_current_user()
        self.test_update_profile()
        self.test_get_sheet_music()
        self.test_get_sheet_music_with_filters()
        self.test_get_lessons()
        self.test_get_lessons_with_filters()
        self.test_dashboard_stats()
        self.test_get_user_progress()
        
        # Test role-based permissions
        self.test_role_based_permissions()
        
        # Switch to teacher user for content creation
        if self.test_user_login("teacher"):
            self.test_create_sheet_music()
            self.test_create_lesson()
            self.test_update_lesson_progress()
            self.test_file_upload_simulation()
        
        # Test unauthorized access
        self.test_unauthorized_access()
        
        # Print final results
        print("\n" + "=" * 50)
        print(f"📊 Test Results: {self.tests_passed}/{self.tests_run} tests passed")
        
        if self.tests_passed == self.tests_run:
            print("🎉 All tests passed!")
            return 0
        else:
            print(f"⚠️  {self.tests_run - self.tests_passed} tests failed")
            return 1

def main():
    tester = ABCMusicLibraryTester()
    return tester.run_comprehensive_tests()

if __name__ == "__main__":
    sys.exit(main())