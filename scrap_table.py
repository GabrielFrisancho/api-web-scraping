import requests
import boto3
import uuid
import json
from datetime import datetime
from botocore.exceptions import ClientError

def lambda_handler(event, context):
    """
    Web scraping function for IGP earthquake data
    Extracts last 10 earthquakes and stores in DynamoDB
    """
    try:
        print("Starting earthquake data scraping...")
        
        # IGP API endpoint for recent earthquakes
        url = "https://ide.igp.gob.pe/arcgis/rest/services/monitoreocensis/SismosReportados/MapServer/0/query"
        
        params = {
            'where': '1=1',  # Get all records
            'outFields': '*',
            'f': 'json', 
            'orderByFields': 'fecha DESC',
            'resultRecordCount': 10
        }
        
        # Make HTTP request to IGP API
        print("Fetching data from IGP API...")
        response = requests.get(url, params=params, timeout=15)
        
        if response.status_code != 200:
            error_msg = f"IGP API returned status {response.status_code}"
            print(error_msg)
            return error_response(500, error_msg)
        
        data = response.json()
        print(f"Received data with {len(data.get('features', []))} features")
        
        if 'features' not in data or not data['features']:
            return error_response(404, "No earthquake data found in response")
        
        # Process earthquake data
        earthquakes = []
        for feature in data['features']:
            attributes = feature.get('attributes', {})
            earthquake = process_earthquake_data(attributes)
            if earthquake:
                earthquakes.append(earthquake)
        
        print(f"Processed {len(earthquakes)} valid earthquakes")
        
        # Store in DynamoDB
        storage_result = store_in_dynamodb(earthquakes)
        
        # Return success response
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'message': f'Successfully processed {len(earthquakes)} earthquakes',
                'count': len(earthquakes),
                'data': earthquakes,
                'storage_result': storage_result
            })
        }
        
    except requests.RequestException as e:
        error_msg = f"Network error: {str(e)}"
        print(error_msg)
        return error_response(500, error_msg)
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        print(error_msg)
        return error_response(500, error_msg)

def process_earthquake_data(attributes):
    """
    Process and clean earthquake data from IGP API
    """
    try:
        # Skip incomplete data
        ref = attributes.get('ref')
        if not ref or ref == 'None' or str(ref).strip() == '':
            return None
        
        # Convert timestamp if needed
        fecha_raw = attributes.get('fecha')
        if isinstance(fecha_raw, (int, float)) and fecha_raw > 0:
            # Convert from milliseconds to datetime
            dt = datetime.fromtimestamp(fecha_raw / 1000)
            fecha = dt.strftime('%Y/%m/%d')
        else:
            fecha = str(fecha_raw) if fecha_raw else ''
        
        # Get magnitude and ensure it's properly formatted
        magnitud = attributes.get('magnitud', '')
        if magnitud is None:
            magnitud = ''
        
        # Create earthquake object
        earthquake = {
            'id': str(uuid.uuid4()),
            'ref': str(ref).strip(),
            'fecha': fecha,
            'hora': str(attributes.get('hora', '')).strip(),
            'magnitud': str(magnitud).strip(),
            'profundidad': f"{attributes.get('prof', '')} km",
            'latitud': str(attributes.get('lat', '')).strip(),
            'longitud': str(attributes.get('lon', '')).strip(),
            'departamento': str(attributes.get('departamento', '')).strip(),
            'scraped_at': datetime.utcnow().isoformat(),
            'objectid': attributes.get('objectid', '')
        }
        
        return earthquake
        
    except Exception as e:
        print(f"Error processing earthquake data: {e}")
        return None

def store_in_dynamodb(earthquakes):
    """
    Store earthquake data in DynamoDB
    Returns success count and any errors
    """
    try:
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('TablaWebScrapping')
        
        success_count = 0
        errors = []
        
        # Batch write new data
        with table.batch_writer() as batch:
            for earthquake in earthquakes:
                try:
                    batch.put_item(Item=earthquake)
                    success_count += 1
                except Exception as e:
                    errors.append(f"Failed to store {earthquake.get('ref', 'unknown')}: {str(e)}")
        
        result = {
            'stored_count': success_count,
            'total_attempted': len(earthquakes)
        }
        
        if errors:
            result['errors'] = errors
            
        print(f"Successfully stored {success_count}/{len(earthquakes)} earthquakes in DynamoDB")
        return result
        
    except ClientError as e:
        error_msg = f"DynamoDB client error: {e.response['Error']['Message']}"
        print(error_msg)
        return {'error': error_msg}
    except Exception as e:
        error_msg = f"Unexpected error storing in DynamoDB: {e}"
        print(error_msg)
        return {'error': error_msg}

def error_response(status_code, message):
    """Helper function for error responses"""
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps({'error': message})
    }
