#!/usr/bin/env python3
"""
Script to convert KuroTools schemas to kurodlc_schema.json format
Analyzes schemas from KuroTools and generates compatible entries for kurodlc_schema.json
"""

import json
import os
import struct
from pathlib import Path
from typing import Dict, List, Tuple, Any

# Mapping KuroTools data types to Python struct format and value type
TYPE_MAPPING = {
    'byte': ('b', 'n', 1),
    'ubyte': ('B', 'n', 1),
    'short': ('h', 'n', 2),
    'ushort': ('H', 'n', 2),
    'int': ('i', 'n', 4),
    'uint': ('I', 'n', 4),
    'long': ('q', 'n', 8),
    'ulong': ('Q', 'n', 8),
    'float': ('f', 'n', 4),
    'toffset': ('Q', 't', 8),  # Text offset (8 bytes)
}

def get_datatype_size(datatype: str | dict) -> int:
    """Calculate size of a datatype from KuroTools schema"""
    if isinstance(datatype, dict):
        # Nested structure
        size = 0
        for _ in range(datatype["size"]):
            for key, value in datatype["schema"].items():
                size += get_datatype_size(value)
        return size
    elif datatype.startswith("data"):
        # Raw data
        if len(datatype) <= 4:
            raise Exception("No size defined for data type")
        else:
            return int(datatype[4:])
    elif datatype.startswith("toffset"):
        return 8  # Offset is always 8 bytes
    elif datatype.endswith("array"):
        # Array: 8 bytes offset + 4 bytes count
        return 12
    else:
        # Standard types
        for base_type, (_, _, size) in TYPE_MAPPING.items():
            if datatype == base_type:
                return size
        raise Exception(f"Unknown data type {datatype}")

def convert_schema_to_struct(schema: dict) -> Tuple[str, List[str], str]:
    """
    Convert KuroTools schema to struct format, keys list, and values string
    Returns: (struct_format, keys_list, values_string)
    """
    struct_parts = []
    keys = []
    values = []
    
    for key, datatype in schema.items():
        keys.append(key)
        
        if isinstance(datatype, dict):
            # Nested structure - flatten it
            for _ in range(datatype["size"]):
                for inner_key, inner_type in datatype["schema"].items():
                    inner_fmt, inner_val, _ = TYPE_MAPPING.get(inner_type, ('I', 'n', 4))
                    struct_parts.append(inner_fmt)
                    values.append(inner_val)
        elif datatype.startswith("toffset"):
            # Text offset
            struct_parts.append('Q')
            values.append('t')
        elif datatype.endswith("array"):
            # Array: offset (8 bytes) + count (4 bytes)
            struct_parts.append('Q')  # offset
            struct_parts.append('I')  # count
            if datatype.startswith("u32"):
                values.append('a')  # 32-bit array
            else:
                values.append('b')  # 16-bit array (default)
        else:
            # Standard type
            fmt, val, _ = TYPE_MAPPING.get(datatype, ('I', 'n', 4))
            struct_parts.append(fmt)
            values.append(val)
    
    struct_format = "<" + "".join(struct_parts)
    values_string = "".join(values)
    
    return struct_format, keys, values_string

def load_kurotools_schemas(schemas_dir: Path) -> Dict[str, Dict]:
    """Load all header schemas from KuroTools"""
    headers_dir = schemas_dir / "headers"
    schemas = {}
    
    if not headers_dir.exists():
        print(f"Headers directory not found: {headers_dir}")
        return schemas
    
    for schema_file in headers_dir.glob("*.json"):
        try:
            with open(schema_file, 'r', encoding='utf-8') as f:
                schema_data = json.load(f)
                table_name = schema_file.stem
                schemas[table_name] = schema_data
        except Exception as e:
            print(f"Error loading {schema_file}: {e}")
    
    return schemas

def convert_kurotools_schema(table_name: str, schema_variants: Dict) -> List[Dict]:
    """
    Convert a KuroTools schema (with multiple variants) to kurodlc_schema format
    Returns list of schema entries (one per variant)
    """
    entries = []
    
    for variant_name, variant_data in schema_variants.items():
        try:
            game_name = variant_data.get("game", variant_name)
            schema = variant_data.get("schema", {})
            
            # Calculate schema size
            total_size = 0
            for key, datatype in schema.items():
                total_size += get_datatype_size(datatype)
            
            # Convert to struct format
            struct_format, keys, values = convert_schema_to_struct(schema)
            
            entry = {
                "info_comment": f"{game_name} - Converted from KuroTools",
                "table_header": table_name,
                "schema_length": total_size,
                "schema": {
                    "schema": struct_format,
                    "sch_len": total_size,
                    "keys": keys,
                    "values": values
                }
            }
            
            # Try to detect primary key from schema
            # Usually "id" is the primary key
            if "id" in keys:
                entry["schema"]["primary_key"] = "id"
            
            entries.append(entry)
            
        except Exception as e:
            print(f"Error converting {table_name} variant {variant_name}: {e}")
    
    return entries

def merge_schemas(existing_schemas: List[Dict], new_schemas: List[Dict]) -> List[Dict]:
    """
    Merge new schemas into existing ones, avoiding duplicates
    Duplicates are detected by table_header + schema_length combination
    """
    # Create index of existing schemas
    existing_index = {
        (schema["table_header"], schema["schema_length"]): schema
        for schema in existing_schemas
    }
    
    merged = list(existing_schemas)
    added_count = 0
    
    for new_schema in new_schemas:
        key = (new_schema["table_header"], new_schema["schema_length"])
        if key not in existing_index:
            merged.append(new_schema)
            added_count += 1
            print(f"  + Added: {new_schema['table_header']} (size: {new_schema['schema_length']})")
        else:
            print(f"  = Exists: {new_schema['table_header']} (size: {new_schema['schema_length']})")
    
    print(f"\nAdded {added_count} new schema(s)")
    return merged

def main():
    # Get current working directory
    current_dir = Path.cwd()
    
    # Paths relative to current directory
    schemas_dir = current_dir / "schemas"
    input_schema_path = current_dir / "kurodlc_schema.json"
    output_schema_path = current_dir / "kurodlc_schema_updated.json"
    report_path = current_dir / "conversion_report.txt"
    
    print("=" * 70)
    print("KuroTools Schema Converter")
    print("=" * 70)
    print(f"\nWorking directory: {current_dir}")
    
    # Load existing kurodlc schema
    print(f"\nLoading existing schema: {input_schema_path}")
    if input_schema_path.exists():
        with open(input_schema_path, 'r', encoding='utf-8') as f:
            existing_schemas = json.load(f)
        print(f"  Loaded {len(existing_schemas)} existing schema(s)")
    else:
        print("  No existing schema found, creating new one")
        existing_schemas = []
    
    # Load KuroTools schemas
    print(f"\nLoading KuroTools schemas from: {schemas_dir}")
    kurotools_schemas = load_kurotools_schemas(schemas_dir)
    print(f"  Found {len(kurotools_schemas)} schema file(s)")
    
    if len(kurotools_schemas) == 0:
        print("\n⚠ WARNING: No schemas found!")
        print("  Make sure the 'schemas' folder with 'headers' subfolder exists")
        print("  in the same directory as this script.")
        input("\nPress Enter to exit...")
        return
    
    # Convert all KuroTools schemas
    print("\nConverting KuroTools schemas...")
    all_new_schemas = []
    for table_name, schema_variants in kurotools_schemas.items():
        converted = convert_kurotools_schema(table_name, schema_variants)
        all_new_schemas.extend(converted)
        if converted:
            print(f"  Converted {table_name}: {len(converted)} variant(s)")
    
    print(f"\nTotal converted schemas: {len(all_new_schemas)}")
    
    # Merge with existing schemas
    print("\nMerging schemas...")
    merged_schemas = merge_schemas(existing_schemas, all_new_schemas)
    
    # Write output
    print(f"\nWriting updated schema to: {output_schema_path}")
    with open(output_schema_path, 'w', encoding='utf-8') as f:
        json.dump(merged_schemas, f, indent=4, ensure_ascii=False)
    
    print(f"\n✓ Done! Total schemas: {len(merged_schemas)}")
    print(f"  Original: {len(existing_schemas)}")
    print(f"  Added: {len(merged_schemas) - len(existing_schemas)}")
    
    # Generate summary report
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("KuroTools Schema Conversion Report\n")
        f.write("=" * 70 + "\n\n")
        f.write(f"Original schemas: {len(existing_schemas)}\n")
        f.write(f"KuroTools schemas found: {len(kurotools_schemas)}\n")
        f.write(f"Converted schemas: {len(all_new_schemas)}\n")
        f.write(f"New schemas added: {len(merged_schemas) - len(existing_schemas)}\n")
        f.write(f"Total schemas: {len(merged_schemas)}\n\n")
        
        f.write("New Schema Tables:\n")
        f.write("-" * 70 + "\n")
        existing_keys = {(s["table_header"], s["schema_length"]) for s in existing_schemas}
        for schema in merged_schemas:
            key = (schema["table_header"], schema["schema_length"])
            if key not in existing_keys:
                f.write(f"  {schema['table_header']:40s} Size: {schema['schema_length']:4d}  Game: {schema['info_comment']}\n")
    
    print(f"\n✓ Report saved to: {report_path}")
    print("=" * 70)
    print("\nPress Enter to exit...")
    input()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        print("\nPress Enter to exit...")
        input()
