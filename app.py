import os
import base64
import psycopg2
from openai import OpenAI
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.utils import secure_filename
import random
import nltk
from nltk.corpus import stopwords
import re
import urllib.parse as up
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
  api_key="OPENAI_KEY")

# Flask setup
app = Flask(__name__)
app.secret_key = "t"  # Use a strong, unique key



#conn = psycopg2.connect(
#    dbname="t",  # Use your existing database name
#    user="t",  # Replace with your PostgreSQL username
#    password="t",  # Replace with your PostgreSQL password
#    host="localhost",  # Default host for local PostgreSQL
#    port=5432  # Default port
#)



DATABASE_URL = os.getenv("DATABASE_URL")  # set this in Render dashboard
conn = psycopg2.connect(DATABASE_URL)

cursor = conn.cursor()

try:
    cursor = conn.cursor()
    cursor.execute("SELECT 1;")
    print("Connected to the database!")
except Exception as e:
    print(f"Database connection failed: {e}")


# Create tables if not exists
cursor.execute("""
CREATE TABLE IF NOT EXISTS images (
    id SERIAL PRIMARY KEY,
    file_name TEXT NOT NULL,
    file_data BYTEA NOT NULL,
    date_uploaded TIMESTAMP DEFAULT NOW(),
    description TEXT
);
""")
conn.commit()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL
);
""")
conn.commit()

# Create favorites table if not exists
cursor.execute("""
CREATE TABLE IF NOT EXISTS favorites (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    image_id INT NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    description TEXT NOT NULL
);
""")
conn.commit()

# Predefined accounts
users = {
    "rileygrace": "0910",
    "sdisorbo": "0910"
}

# Create users table if it doesn't exist
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL
);
""")
conn.commit()

# Insert predefined users if not already in DB
for username, password in users.items():
    cursor.execute("SELECT 1 FROM users WHERE username = %s", (username,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, password))
conn.commit()


def generate_image_description(base64_image):
    """Uses GPT-4 Vision to generate a description for an image."""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Use GPT-4 Vision model
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this image:"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }
            ],
            max_tokens=300
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error generating description: {e}")
        return "No description available."
    
def ensure_full_permissions():
    try:
        cursor = conn.cursor()
        
        # Ensure users have permissions on all tables
        for user in ['rileygrace', 'sdisorbo']:
            cursor.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_roles
                    WHERE rolname = '{user}'
                ) THEN
                    CREATE ROLE {user} LOGIN PASSWORD '0910';
                END IF;
            END $$;

            GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO {user};
            GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO {user};
            GRANT USAGE ON SCHEMA public TO {user};
            ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {user};
            ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO {user};
            """)
        
        conn.commit()
        print("Permissions for 'rileygrace' and 'sdisorbo' ensured successfully.")
    except Exception as e:
        conn.rollback()
        print(f"Error ensuring permissions: {e}")
    finally:
        cursor.close()


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        # Ensure session key is set for valid users
        if username in users and users[username] == password:
            session['user'] = username  # Store username in session
            cursor.execute("SELECT id FROM users WHERE username = %s", (session['user'],))
            user_id = cursor.fetchone()

            if not user_id:
                flash("User not found.", "danger")
                return redirect(url_for('login'))
            session['user_id'] = user_id[0]  # Store user ID in session
    
            return redirect(url_for('home'))  # Redirect to home
        else:
            flash("Invalid username or password.", "danger")

    return render_template('login.html')  # Stay on login page if invalid

@app.route('/remove_favorite/<int:favorite_id>', methods=['POST'])
def remove_favorite(favorite_id):
    user = session.get('user')
    if not user:
        return jsonify({"error": "User not logged in"}), 401

    try:
        # Fetch user_id from the session username
        cursor.execute("SELECT id FROM users WHERE username = %s", (user,))
        user_id = cursor.fetchone()
        if not user_id:
            return jsonify({"error": "User not found"}), 404

        user_id = user_id[0]
       
        # Delete the favorite from the database
        cursor.execute(
            "DELETE FROM favorites WHERE image_id = %s AND user_id = %s",
            (favorite_id, user_id)
        )
        conn.commit()
        print(f"Favorite {favorite_id} removed successfully")
        return jsonify({"message": "Favorite removed successfully"}), 200

    except Exception as e:
        conn.rollback()
        print(f"Error removing favorite: {e}")
        return jsonify({"error": "An error occurred while removing the favorite"}), 500


@app.route('/toggle_favorite', methods=['POST'])
def toggle_favorite():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'User not logged in'}), 403
    #get user ID
    user_id = session['user_id']
    print("User ID ", user_id)
    

    data = request.get_json()
    image_id = data.get('image_id')
    if not image_id:
        return jsonify({'success': False, 'message': 'Invalid image ID'}), 400

    try:
        cursor = conn.cursor()
        
        # Check if the favorite already exists
        cursor.execute("""
        SELECT id FROM favorites WHERE user_id = %s AND image_id = %s
        """, (user_id, image_id))
        favorite = cursor.fetchone()

        if favorite:
            # If the favorite exists, delete it (toggle off)
            cursor.execute("""
            DELETE FROM favorites WHERE id = %s
            """, (favorite[0],))
            conn.commit()
            return jsonify({'success': True, 'message': 'Removed from favorites'})
        else:
            # Otherwise, add the favorite (toggle on)
            cursor.execute("""
            INSERT INTO favorites (user_id, image_id, description)
            SELECT %s, %s, description FROM images WHERE id = %s
            """, (user_id, image_id, image_id))
            conn.commit()
            return jsonify({'success': True, 'message': 'Added to favorites'})
    except Exception as e:
        conn.rollback()  # Roll back the transaction to reset the state
        print(f"Error toggling favorite: {e}")
        return jsonify({'success': False, 'message': 'An error occurred'}), 500
    finally:
        cursor.close()



@app.route('/logout')
def logout():
    session.pop('user', None)  # Remove user from session
    return redirect(url_for('login'))

@app.route('/profile')
def profile():
    user = session.get('user')  # Get the logged-in username
    if not user:
        flash("Please log in to view your profile.", "danger")
        return redirect(url_for('login'))

    try:
        print(user)
        # Fetch the user_id based on the username
        cursor.execute("SELECT id FROM users WHERE username = %s", (user,))
        user_id = cursor.fetchone()
        if not user_id:
            flash("User not found.", "danger")
            return redirect(url_for('login'))
        
        user_id = user_id[0]  # Extract the ID from the tuple
        print(user_id)

         # Fetch favorite images and their descriptions for the user
        cursor.execute("""
            SELECT images.id, images.file_data, images.description 
            FROM images 
            INNER JOIN favorites ON images.id = favorites.image_id 
            WHERE favorites.user_id = %s
        """, (user_id,))
        favorite_images = cursor.fetchall()

        # Convert images to a format suitable for HTML rendering
        favorites_data = [
            {
                "id": fav[0],
                "description": fav[2],
                "data": base64.b64encode(fav[1]).decode('utf-8')  # Encode file_data
            }
            for fav in favorite_images
        ]


        return render_template('profile.html', favorites=favorites_data, user=user, username=user)
    
    except Exception as e:
        conn.rollback()  # Reset transaction if an error occurs
        print(f"Error loading profile: {e}")
        flash("An error occurred while loading your profile.", "danger")
        return redirect(url_for('home'))

    finally:
        conn.commit()  # Commit any changes if no error occurs


# Routes

@app.route('/')
def home():
    try:
        cursor = conn.cursor()
        # Fetch all images from the database
        cursor.execute("SELECT file_data FROM images")
        images = cursor.fetchall()
        # Convert binary data (memoryview) to Base64
        all_pictures = [base64.b64encode(bytes(image[0])).decode('utf-8') for image in images]

        return render_template('collage.html', selected_pictures=all_pictures)
    except Exception as e:
        conn.rollback()  # Rollback the transaction
        print(f"Error fetching images: {e}")
        flash("An error occurred while loading images.", "danger")
        return render_template('collage.html', pictures=[])
    finally:
        conn.commit()  # Ensure all changes are committed (or rolled back earlier)



@app.route('/delete_image', methods=['POST'])
def delete_image():
    data = request.get_json()
    image_id = data.get('image_id')

    if not image_id:
        return jsonify({"success": False, "message": "No image ID provided."})

    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM images WHERE id = %s", (image_id,))
        conn.commit()
        cursor.close()
        return jsonify({"success": True, "message": "Image deleted successfully."})
    except Exception as e:
        print(f"Error deleting image: {e}")
        return jsonify({"success": False, "message": "Error deleting image."})


@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        uploaded_files = request.files.getlist('files')  # Handle multiple file uploads
        cursor = conn.cursor()

        for uploaded_file in uploaded_files:
            if uploaded_file and uploaded_file.filename:
                filename = secure_filename(uploaded_file.filename)
                file_ext = os.path.splitext(filename)[1].lower()

                if file_ext in ['.jpg', '.jpeg', '.png']:
                    # Save image as binary
                    file_data = uploaded_file.read()

                    # Generate description using GPT-4 with Vision
                    base64_image = base64.b64encode(file_data).decode('utf-8')
                    description = generate_image_description(base64_image)

                    # Insert image and description into the database
                    cursor.execute(
                        "INSERT INTO images (file_name, file_data, description) VALUES (%s, %s, %s)",
                        (filename, psycopg2.Binary(file_data), description)
                    )
                else:
                    return f"Unsupported file type: {filename}", 400

        conn.commit()
        return "Files uploaded successfully and descriptions added!", 200

    return render_template('upload.html')

@app.route('/view', methods=['GET', 'POST'])
def view_page():
    if request.method == 'POST':
        user_input = request.json.get('description')  # Get user input

        # Fetch image descriptions from the database
        cursor = conn.cursor()
        cursor.execute("SELECT id, file_name, description FROM images")
        images = cursor.fetchall()

        # If there are no descriptions, return an empty list
        if not images:
            return jsonify([])
        
        #only go through images that have a matching word to the description after making the desc and user input lowercase and removing stop words and char
        images = [img for img in images if any(word in re.sub(r'\W+', ' ', img[2].lower()) for word in re.sub(r'\W+', ' ', user_input.lower()).split() if word not in stopwords.words('english'))]
        #if there are no images that match the description return an empty list
        if not images:
            return jsonify([])
        
        if len(images) > 10:
            # Create GPT prompt for finding similar descriptions
            prompt = f"""
            The user provided this description: "{user_input}".
            Match it to the most similar descriptions from the following list of images:

            """
            for img in images:
                prompt += f"Image ID: {img[0]}, Name: {img[1]}, Description: {img[2] or 'No description yet'}\n"

            prompt += "\nReturn the IDs of the most similar 1-10 images in descending order of similarity. Only return the IDs as a list, like 14, 3, 6 for example. Don't include explanations or anything else."

            # Call OpenAI GPT to rank descriptions
            response = client.chat.completions.create(
                model="gpt-4o-mini",  # Use GPT-4 model for text-based tasks
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200
            )
            # Parse GPT response to extract matched IDs
            gpt_output = response.choices[0].message.content
            gpt_output = list(filter(lambda x: x in '0123456789,', gpt_output))
            #turn the list into a string
            match_ids = ''.join(gpt_output)
            #split the string into a list
            match_ids = match_ids.split(',')
        else:
            match_ids = [img[0] for img in images]
        #if the list is empty or invalid return an empty list
        if not match_ids:
            return jsonify([])
        # Fetch matching images from the database
        matched_images = []
        for img_id in match_ids[:10]:  # Limit to top 10 matches
            cursor.execute("SELECT id, file_name, file_data, description FROM images WHERE id = %s", (img_id,))
            img = cursor.fetchone()
            if img:
                matched_images.append({
                    "id": img[0],
                    "name": img[1],
                    "data": base64.b64encode(img[2]).decode('utf-8'),
                    "description": img[3] or "No description yet"
                })
        return jsonify(matched_images)

    return render_template('view.html')


@app.route('/edit_description', methods=['POST'])
def edit_description():
    image_id = request.json.get('image_id')
    new_description = request.json.get('description')

    cursor = conn.cursor()
    cursor.execute("UPDATE images SET description = %s WHERE id = %s", (new_description, image_id))
    conn.commit()

    return jsonify({"status": "success", "message": "Description updated successfully!"})


@app.route('/download/<int:file_id>/<string:file_type>')
def download(file_id, file_type):
    if file_type == 'image':
        cursor.execute("SELECT file_name, file_data FROM images WHERE id = %s", (file_id,))
        result = cursor.fetchone()
        file_name, file_data = result
        response = app.response_class(file_data, mimetype='application/octet-stream')
        response.headers['Content-Disposition'] = f'attachment; filename={file_name}'
        return response

    elif file_type == 'text':
        cursor.execute("SELECT file_name, file_content FROM texts WHERE id = %s", (file_id,))
        result = cursor.fetchone()
        file_name, file_content = result
        response = app.response_class(file_content, mimetype='text/plain')
        response.headers['Content-Disposition'] = f'attachment; filename={file_name}'
        return response

if __name__ == '__main__':
    ensure_full_permissions()  # Set up permissions for specific users
    app.run(debug=True)
