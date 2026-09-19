"""
lib_texture_loader.py - Utility for loading and converting DDS textures
Supports loading from multiple directory structures

Texture files come in three wrappers, all handled transparently by
read_dds_bytes() / unwrap_dds():
  - plain DDS ("DDS ")                          Kuro / Daybreak, loose mods
  - LZ4 frame (04 22 4D 18) holding a DDS       Trails in the Sky 1st / 2nd
                                                Chapter remakes (and their .pac)
  - CLE: Blowfish (F9BA / C9BA) or zstd (D9BA)  Kuro / Daybreak game files
LZ4 needs the lz4 module (python -m pip install lz4); CLE needs blowfish and
zstandard, taken from kuro_mdl_export_meshes.decryptCLE.
"""

import os
import io
import struct
from pathlib import Path
from typing import Optional, Dict, Tuple
import base64

try:
    from PIL import Image
except ImportError:
    Image = None
    print("Warning: PIL not installed. DDS conversion will be limited.")

try:
    import lz4.frame as _lz4_frame
except ImportError:
    _lz4_frame = None

DDS_MAGIC = b'DDS '
LZ4_MAGIC = b'\x04\x22\x4D\x18'
CLE_MAGICS = (b'F9BA', b'C9BA', b'D9BA')


class TextureWrapperError(ValueError):
    """The file is a known texture wrapper that cannot be opened here."""


def texture_wrapper(data: bytes) -> str:
    """'dds', 'lz4', 'cle' or 'unknown' - what the bytes of a texture file are."""
    head = data[:4]
    if head == DDS_MAGIC:
        return 'dds'
    if head == LZ4_MAGIC:
        return 'lz4'
    if head in CLE_MAGICS:
        return 'cle'
    return 'unknown'


def unwrap_dds(data: bytes) -> bytes:
    """Return the plain DDS inside `data`, whatever it is wrapped in.

    Raises TextureWrapperError with a readable reason when the wrapper is
    known but cannot be opened (module missing, damaged frame, no DDS inside).
    """
    kind = texture_wrapper(data)
    if kind == 'dds':
        return data
    if kind == 'lz4':
        if _lz4_frame is None:
            raise TextureWrapperError(
                "LZ4-compressed texture (Trails in the Sky 2nd Chapter) - "
                "install the lz4 module: python -m pip install lz4")
        try:
            data = _lz4_frame.decompress(data)
        except Exception as e:
            raise TextureWrapperError("LZ4 frame does not decompress: {}".format(e))
    elif kind == 'cle':
        try:
            from kuro_mdl_export_meshes import decryptCLE
        except Exception as e:
            raise TextureWrapperError(
                "Kuro CLE texture - decryptCLE unavailable ({})".format(e))
        data = decryptCLE(data)
    else:
        raise TextureWrapperError("not a DDS texture (starts with {!r})".format(data[:4]))
    if data[:4] != DDS_MAGIC:
        raise TextureWrapperError("unwrapped, but the contents are not a DDS")
    return data


def read_dds_bytes(path) -> bytes:
    """Read a texture file and return plain DDS bytes (see unwrap_dds)."""
    with open(path, 'rb') as f:
        return unwrap_dds(f.read())


class DDSHeader:
    """DDS file header parser (accepts LZ4 / CLE wrapped textures too)"""
    def __init__(self, data: bytes):
        if data[:4] != DDS_MAGIC:
            data = unwrap_dds(data)
        if data[:4] != DDS_MAGIC:
            raise ValueError("Not a valid DDS file")
        
        # Read DDS_HEADER
        # size, flags, height, width, pitch, depth, mipmaps (the rest of the
        # 124-byte header follows; the pixel format is read below)
        header = struct.unpack_from('<7I', data, 4)
        self.size = header[0]
        self.flags = header[1]
        self.height = header[2]
        self.width = header[3]
        self.pitch_or_linear_size = header[4]
        self.depth = header[5]
        self.mipmap_count = header[6]
        
        # Read DDS_PIXELFORMAT
        pf = struct.unpack('<2I4s5I', data[76:108])
        self.pf_size = pf[0]
        self.pf_flags = pf[1]
        self.pf_fourcc = pf[2]
        self.pf_rgb_bit_count = pf[3]
        
    def __repr__(self):
        return f"DDS({self.width}x{self.height}, format={self.pf_fourcc})"


def find_texture_file(texture_name: str, search_paths: list) -> Optional[Path]:
    """
    Find texture file in multiple possible locations.
    
    Args:
        texture_name: Name of texture (without or with .dds extension)
        search_paths: List of paths to search in
        
    Returns:
        Path to texture file or None if not found
    """
    # Ensure .dds extension
    if not texture_name.lower().endswith('.dds'):
        texture_name = texture_name + '.dds'
    
    # Try each search path
    for base_path in search_paths:
        base_path = Path(base_path)
        
        # Direct path
        direct = base_path / texture_name
        if direct.exists():
            return direct
            
        # In 'image' subdirectory
        in_image = base_path / 'image' / texture_name
        if in_image.exists():
            return in_image
            
        # In 'textures' subdirectory
        in_textures = base_path / 'textures' / texture_name
        if in_textures.exists():
            return in_textures
    
    return None


def convert_dds_to_png_pil(dds_data: bytes) -> Optional[bytes]:
    """
    Convert DDS to PNG using PIL (supports common formats).
    
    Args:
        dds_data: Raw DDS file bytes
        
    Returns:
        PNG bytes or None if conversion failed
    """
    if Image is None:
        return None
    
    try:
        dds_data = unwrap_dds(dds_data)
        # Try to open with PIL's DDS plugin
        img = Image.open(io.BytesIO(dds_data))
        
        # Convert to PNG
        output = io.BytesIO()
        img.save(output, format='PNG')
        return output.getvalue()
        
    except Exception as e:
        print(f"PIL DDS conversion failed: {e}")
        return None


def convert_dds_to_rgba_raw(dds_data: bytes) -> Optional[Tuple[int, int, bytes]]:
    """
    Simple DDS to RGBA converter for common uncompressed formats.
    
    Args:
        dds_data: Raw DDS file bytes
        
    Returns:
        Tuple of (width, height, rgba_bytes) or None if format not supported
    """
    try:
        dds_data = unwrap_dds(dds_data)
        header = DDSHeader(dds_data)
        
        # Calculate data offset (header is 128 bytes)
        data_offset = 128
        
        # Handle DXT/BC compressed formats
        fourcc = header.pf_fourcc
        
        if fourcc == b'DXT1':
            # DXT1/BC1 - 4x4 blocks, 8 bytes per block
            print(f"DXT1 format detected - conversion not implemented yet")
            return None
            
        elif fourcc == b'DXT3':
            # DXT3/BC2 - 4x4 blocks, 16 bytes per block
            print(f"DXT3 format detected - conversion not implemented yet")
            return None
            
        elif fourcc == b'DXT5':
            # DXT5/BC3 - 4x4 blocks, 16 bytes per block
            print(f"DXT5 format detected - conversion not implemented yet")
            return None
            
        # Uncompressed formats
        elif header.pf_rgb_bit_count == 32:
            # Likely RGBA8888
            pixel_data = dds_data[data_offset:]
            return (header.width, header.height, pixel_data)
            
        elif header.pf_rgb_bit_count == 24:
            # RGB888 - need to add alpha channel
            print(f"RGB24 format detected - conversion not fully implemented")
            return None
            
        else:
            print(f"Unsupported DDS format: fourcc={fourcc}, bpp={header.pf_rgb_bit_count}")
            return None
            
    except Exception as e:
        print(f"DDS parsing failed: {e}")
        return None


def load_texture_as_data_url(texture_name: str, search_paths: list) -> Optional[str]:
    """
    Load texture and convert to data URL for embedding in HTML.
    
    Args:
        texture_name: Name of texture file
        search_paths: List of paths to search
        
    Returns:
        Data URL string (data:image/png;base64,...) or None
    """
    # Find the texture file
    texture_path = find_texture_file(texture_name, search_paths)
    if texture_path is None:
        print(f"Texture not found: {texture_name}")
        return None
    
    print(f"Loading texture: {texture_path}")
    
    try:
        with open(texture_path, 'rb') as f:
            dds_data = f.read()
        
        # Try PIL conversion first (most reliable)
        png_data = convert_dds_to_png_pil(dds_data)
        
        if png_data is not None:
            # Convert to base64 data URL
            b64 = base64.b64encode(png_data).decode('ascii')
            return f"data:image/png;base64,{b64}"
        else:
            print(f"Could not convert {texture_name} to PNG")
            return None
            
    except Exception as e:
        print(f"Error loading texture {texture_name}: {e}")
        return None


def load_material_textures(material_info: dict, image_list: list, search_paths: list) -> Dict[str, dict]:
    """
    Load all textures referenced by materials.
    
    Args:
        material_info: Material info from JSON (list of materials)
        image_list: List of image names from image_list.json
        search_paths: Paths to search for textures
        
    Returns:
        Dictionary mapping texture names to texture data
        {
            'texture_name': {
                'data_url': 'data:image/png;base64,...',
                'width': 1024,
                'height': 1024
            }
        }
    """
    texture_cache = {}
    
    # Get unique texture names from materials
    unique_textures = set()
    for material in material_info:
        for tex in material.get('textures', []):
            tex_name = tex['texture_image_name']
            if not tex_name.endswith('.dds'):
                tex_name = tex_name + '.dds'
            unique_textures.add(tex_name)
    
    print(f"\nLoading {len(unique_textures)} unique textures...")
    
    # Load each texture
    for tex_name in sorted(unique_textures):
        data_url = load_texture_as_data_url(tex_name, search_paths)
        if data_url:
            texture_cache[tex_name] = {
                'data_url': data_url,
                'loaded': True
            }
            print(f"  ✓ {tex_name}")
        else:
            texture_cache[tex_name] = {
                'data_url': None,
                'loaded': False
            }
            print(f"  ✗ {tex_name} - failed to load")
    
    return texture_cache


def create_material_texture_map(material_info: dict, texture_cache: Dict[str, dict]) -> Dict[str, dict]:
    """
    Create mapping of material names to their textures.
    
    Args:
        material_info: Material info from JSON
        texture_cache: Loaded texture cache
        
    Returns:
        Dictionary mapping material names to texture info
        {
            'material_name': {
                'diffuse': 'data:image/png;base64,...',
                'normal': 'data:image/png;base64,...',
                'specular': 'data:image/png;base64,...',
            }
        }
    """
    material_map = {}
    
    for material in material_info:
        mat_name = material['material_name']
        mat_textures = {}
        
        for tex in material.get('textures', []):
            tex_name = tex['texture_image_name']
            if not tex_name.endswith('.dds'):
                tex_name = tex_name + '.dds'
            
            slot = tex['texture_slot']
            
            # Get texture data from cache
            if tex_name in texture_cache and texture_cache[tex_name]['loaded']:
                data_url = texture_cache[tex_name]['data_url']
                
                # Map texture slots to material properties
                # Common slots: 0=diffuse, 3=normal, 7=specular, 9=toon
                if slot == 0:
                    mat_textures['diffuse'] = data_url
                elif slot == 1:
                    mat_textures['detail'] = data_url
                elif slot == 3:
                    mat_textures['normal'] = data_url
                elif slot == 7:
                    mat_textures['specular'] = data_url
                elif slot == 9:
                    mat_textures['toon'] = data_url
                else:
                    mat_textures[f'slot_{slot}'] = data_url
        
        if mat_textures:
            material_map[mat_name] = mat_textures
    
    return material_map
