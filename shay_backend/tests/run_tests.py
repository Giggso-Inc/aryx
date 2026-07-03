#!/usr/bin/env python3
"""
Test runner script for embedd_type functionality tests
"""

import subprocess
import sys
import os

def run_tests():
    """Run all tests related to embedd_type functionality"""
    
    # Add the parent directory to Python path
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, parent_dir)
    
    # Test files to run
    test_files = [
        "tests/test_ml_service_embedd_type.py",
        "tests/test_datasources_embedd_type.py", 
        "tests/test_database_schema.py"
    ]
    
    print("🧪 Running embedd_type functionality tests...")
    print("=" * 60)
    
    for test_file in test_files:
        print(f"\n📁 Running {test_file}...")
        print("-" * 40)
        
        try:
            result = subprocess.run([
                sys.executable, "-m", "pytest", 
                test_file, 
                "-v", 
                "--tb=short"
            ], capture_output=True, text=True, cwd=parent_dir)
            
            print(result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)
            
            if result.returncode != 0:
                print(f"❌ Tests in {test_file} failed")
            else:
                print(f"✅ Tests in {test_file} passed")
                
        except Exception as e:
            print(f"❌ Error running {test_file}: {e}")
    
    print("\n" + "=" * 60)
    print("🏁 Test run completed!")

if __name__ == "__main__":
    run_tests()
