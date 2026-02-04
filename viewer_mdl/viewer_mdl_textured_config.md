# ⚙️ Viewer Configuration

The viewer now has **configurable constants** directly in the HTML file that you can easily modify!

## 📍 Where to Find Configuration

After running the viewer, a temporary HTML file is created. At the beginning of the `<script>` section, you'll find:

```javascript
// ============================================================
// CONFIGURATION - Adjust these values as needed
// ============================================================
const CONFIG = {
  CAMERA_ZOOM: 1.0,           // Camera zoom factor
  AUTO_HIDE_SHADOW: true,      // Automatically hide shadow meshes
  INITIAL_BACKGROUND: 0x1a1a2e // Background color
};
// ============================================================
```

## 🎯 CAMERA_ZOOM - Zoom Settings

**Default value:** `1.0`

### What it does:
Controls how close/far the camera is from the model on load.

### Values:
```javascript
CAMERA_ZOOM: 1.0    // Tight fit (model fills ~100% viewport)
CAMERA_ZOOM: 0.95   // Zoomed in more (recommended!)
CAMERA_ZOOM: 0.9    // Even more zoomed in
CAMERA_ZOOM: 0.85   // Very close
CAMERA_ZOOM: 0.8    // Extremely close (may clip large models)

CAMERA_ZOOM: 1.1    // Further away (10% padding)
CAMERA_ZOOM: 1.2    // Quite far (20% padding)
CAMERA_ZOOM: 1.5    // Very far
```

### How to change:
1. Run the viewer normally
2. HTML is created in `C:\Users\...\AppData\Local\Temp\mdl_viewer_XXX\`
3. **OR** edit directly in the Python script:

```python
# In viewer_mdl_textured_v2.py file, find the line:
const CONFIG = {{
  CAMERA_ZOOM: 1.0,           # ← Change here!
```

Change to:
```python
const CONFIG = {{
  CAMERA_ZOOM: 0.95,          # More zoomed in
```

### Recommended values:
- **Characters:** `0.95` - `0.9`
- **Large objects (vehicles):** `1.0` - `1.1`  
- **Small objects (items):** `0.85` - `0.8`
- **Scenes (full scenes):** `1.2` - `1.5`

---

## 👻 AUTO_HIDE_SHADOW - Automatic Shadow Hiding

**Default value:** `true`

### What it does:
Automatically hides all meshes containing "shadow" in their name on load.

### Values:
```javascript
AUTO_HIDE_SHADOW: true   // Shadow meshes are hidden (recommended)
AUTO_HIDE_SHADOW: false  // Shadow meshes are visible
```

### Examples of meshes that will be hidden:
- `0_chr9999_shadow_00`
- `ground_shadow`
- `character_shadow_plane`

---

## 🎨 INITIAL_BACKGROUND - Background Color

**Default value:** `0x1a1a2e` (dark blue)

### What it does:
Sets the scene background color.

### Values (hex color):
```javascript
INITIAL_BACKGROUND: 0x1a1a2e  // Dark blue (default)
INITIAL_BACKGROUND: 0x000000  // Black
INITIAL_BACKGROUND: 0xffffff  // White
INITIAL_BACKGROUND: 0x222222  // Dark gray
INITIAL_BACKGROUND: 0x2a2a3e  // Dark purple
INITIAL_BACKGROUND: 0x1e3a5f  // Dark blue
INITIAL_BACKGROUND: 0x87ceeb  // Sky blue
```

### Online color picker:
Use https://www.w3schools.com/colors/colors_picker.asp
- Select a color
- Copy the HEX code (e.g., `#87ceeb`)
- Use as `0x87ceeb` (replace `#` with `0x`)

---

## 🔧 How to Edit Permanently

### Option A: Edit Python Script (recommended)

Open `viewer_mdl_textured_v2.py` in a text editor and find:

```python
const CONFIG = {{
  CAMERA_ZOOM: 1.0,
  AUTO_HIDE_SHADOW: true,
  INITIAL_BACKGROUND: 0x1a1a2e
}};
```

Change the values as needed:

```python
const CONFIG = {{
  CAMERA_ZOOM: 0.9,              # More zoom
  AUTO_HIDE_SHADOW: true,         # Hide shadows
  INITIAL_BACKGROUND: 0x000000    # Black background
}};
```

Save and run the viewer again.

### Option B: Edit Temporary HTML (for one-time use)

1. Run the viewer
2. Window opens, but **don't** close it
3. Find temp HTML: `C:\Users\...\AppData\Local\Temp\mdl_viewer_XXX\`
4. Open HTML in text editor
5. Find and change `CONFIG`
6. Save HTML
7. Refresh page in browser (F5)

---

## 📊 Example Configurations

### For characters:
```javascript
const CONFIG = {
  CAMERA_ZOOM: 0.9,            // Close up, detail on face
  AUTO_HIDE_SHADOW: true,       // No shadows
  INITIAL_BACKGROUND: 0x1a1a2e  // Dark background
};
```

### For large objects (mechs, vehicles):
```javascript
const CONFIG = {
  CAMERA_ZOOM: 1.1,            // Further away
  AUTO_HIDE_SHADOW: false,      // Show shadows
  INITIAL_BACKGROUND: 0x2a2a3e  // Dark purple
};
```

### For presentation (screenshots):
```javascript
const CONFIG = {
  CAMERA_ZOOM: 0.95,           // Nice zoom
  AUTO_HIDE_SHADOW: true,       // Clean look
  INITIAL_BACKGROUND: 0xffffff  // White background for transparency
};
```

### For technical analysis:
```javascript
const CONFIG = {
  CAMERA_ZOOM: 1.2,            // See entire model
  AUTO_HIDE_SHADOW: false,      // See all meshes
  INITIAL_BACKGROUND: 0x222222  // Neutral gray
};
```

---

## 🎮 Runtime Changes (future feature)

In a future version, UI controls could be added:

```
Controls:
├── Camera Zoom: [────○────] (slider)
├── [ ] Show Shadows (checkbox)
└── Background: [color picker]
```

Let me know if you'd like this implemented!

---

## 💡 Tips

1. **Start with `CAMERA_ZOOM: 0.95`** - good compromise
2. **For each model type** you can create your own version of the script
3. **Save favorite configurations** in comments in the script
4. **Use Reset Camera** button after changing zoom factor

---

## ⚡ Quick Reference

| Need | CAMERA_ZOOM | AUTO_HIDE_SHADOW | BACKGROUND |
|------|-------------|------------------|------------|
| Character detail | 0.9 | true | 0x1a1a2e |
| Full character | 1.0 | true | 0x1a1a2e |
| Large object | 1.1 | false | 0x2a2a3e |
| Screenshot | 0.95 | true | 0xffffff |
| Technical analysis | 1.2 | false | 0x222222 |

---

**Recommendation for your use:**
```javascript
const CONFIG = {
  CAMERA_ZOOM: 0.9,     // ← Try this for more zoom!
  AUTO_HIDE_SHADOW: true,
  INITIAL_BACKGROUND: 0x1a1a2e
};
```
