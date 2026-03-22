import sys
import os

# Ajouter la racine du projet au path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app import app

# Vercel utilise "app"
