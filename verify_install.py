#!/usr/bin/env python3
"""
Verify Installation Script
Überprüft, ob alle erforderlichen Abhängigkeiten installiert sind.
"""

import sys

def check_imports():
    """Überprüft alle erforderlichen Importe"""
    errors = []
    
    required_modules = [
        ('dotenv', 'python-dotenv'),
        ('pydantic', 'pydantic'),
        ('google.genai', 'google-genai'),
        ('py_clob_client', 'py-clob-client'),
        ('dateutil', 'python-dateutil'),
        ('requests', 'requests'),
    ]
    
    print("🔍 Überprüfe Installation der Abhängigkeiten...\n")
    
    for module_name, package_name in required_modules:
        try:
            __import__(module_name)
            print(f"✅ {package_name}: OK")
        except ImportError as e:
            print(f"❌ {package_name}: FEHLT")
            errors.append(package_name)
    
    print("\n" + "="*50)
    
    if errors:
        print(f"\n❌ {len(errors)} Paket(e) fehlt/fehlen:")
        for pkg in errors:
            print(f"   - {pkg}")
        print("\nBitte führen Sie aus:")
        print("  pip install -r requirements.txt")
        return False
    else:
        print("\n✅ Alle Abhängigkeiten sind installiert!")
        print("Sie können jetzt 'python main.py' ausführen.")
        return True

if __name__ == "__main__":
    success = check_imports()
    sys.exit(0 if success else 1)
