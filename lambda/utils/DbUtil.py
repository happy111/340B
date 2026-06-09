import pandas as pd
from functools import lru_cache
from sqlalchemy import create_engine, Column, String, Float, Date, DateTime, Boolean, Integer, text, desc, func, cast
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.engine import URL
from snowflake.sqlalchemy import URL as SnowflakeURL
from datetime import datetime
import os
import secrets
import boto3
import json
from botocore.exceptions import ClientError
import re
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
import snowflake.connector

# Custom exception classes for database operations
class DatabaseError(Exception):
    """Base exception for database-related errors"""
    pass

class DatabaseConnectionError(DatabaseError):
    """Exception raised when database connection fails"""
    pass

class DatabaseConfigurationError(DatabaseError):
    """Exception raised when database configuration is invalid"""
    pass

class DatabaseQueryError(DatabaseError):
    """Exception raised when database query fails"""
    pass

class DatabaseTimeoutError(DatabaseError):
    """Exception raised when database query times out"""
    pass

from sqlalchemy.ext.hybrid import hybrid_property

# Define ORM base
Base = declarative_base()
    
class AnomalyScore(Base):
    __tablename__ = '340B_Anomalies'

    Anomaly_ID = Column(Integer, primary_key=True)
    Anomaly_Brand = Column(String(255))
    Anomaly_340BID = Column(String(50))
    Anomaly_CoveredEntity = Column(String(255))
    Anomaly_Date = Column(Date)
    Anomaly_Status = Column(String(50))
    Anomaly_LinkageScore = Column(Integer)
    Anomaly_WAC = Column(Float)
    Anomaly_ChargeBack = Column(Float)
    Anomaly_Units = Column(Integer)
    Anomaly_CreatedDate = Column(Date)
    Anomaly_LastModifiedDate = Column(Date)
    
    # Hybrid properties for backward compatibility with existing code
    # These can be used in both Python code and SQL queries
    
    @hybrid_property
    def _340B_Id(self):
        return self.Anomaly_340BID
    
    @_340B_Id.expression
    def _340B_Id(cls):
        return cls.Anomaly_340BID
    
    @hybrid_property
    def Dollars(self):
        return self.Anomaly_WAC
    
    @Dollars.expression
    def Dollars(cls):
        return cls.Anomaly_WAC
    
    @hybrid_property
    def Anomaly_Score(self):
        # Map LinkageScore to Anomaly_Score (using a threshold approach)
        # LinkageScore >= 50 is considered an anomaly (score >= 2)
        if self.Anomaly_LinkageScore is not None:
            return 2 if self.Anomaly_LinkageScore >= 50 else 1
        return 0
    
    @Anomaly_Score.expression
    def Anomaly_Score(cls):
        # SQL expression for Anomaly_Score based on LinkageScore
        # LinkageScore >= 50 maps to score 2, otherwise 1
        from sqlalchemy import case
        return case(
            (cls.Anomaly_LinkageScore >= 50, 2),
            else_=1
        )
    
    @hybrid_property
    def EntityName(self):
        return self.Anomaly_CoveredEntity
    
    @EntityName.expression
    def EntityName(cls):
        return cls.Anomaly_CoveredEntity
    
    @hybrid_property
    def Brand(self):
        return self.Anomaly_Brand
    
    @Brand.expression
    def Brand(cls):
        return cls.Anomaly_Brand
    
    @hybrid_property
    def State(self):
        # State needs to be joined from HRSA table
        # This property is for instance access only
        return None
    
    # Note: State will need to be joined from HRSA table in queries

# Global variables for lazy initialization
_engine = None
_Session = None
_database_url_cache = None

def get_secret(secret_name, region_name='us-east-1'):
    """
    Retrieve database URL from AWS Secrets Manager.
    
    Args:
        secret_name: ARN or name of the secret
        region_name: AWS region (default: us-east-1)
    
    Returns:
        Database URL string
    """
    global _database_url_cache
    
    # Return cached value if available (avoid repeated Secrets Manager calls)
    if _database_url_cache:
        return _database_url_cache
    
    # Create a Secrets Manager client
    client = boto3.client('secretsmanager', region_name=region_name)

    try:
        response = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        print(f"Error retrieving secret: {e}")
        return None

    # Secrets can be either a string or binary
    if 'SecretString' in response:
        secret = response['SecretString']
        secret_dict = json.loads(secret)
        
        # Handle different secret formats
        if 'DB_URL' in secret_dict:
            # Custom format with DB_URL field
            _database_url_cache = secret_dict['DB_URL']
        elif 'host' in secret_dict and 'username' in secret_dict:
            # RDS auto-generated format - use SQLAlchemy URL builder with mysql-connector-python driver
            from sqlalchemy.engine import URL
            _database_url_cache = URL.create(
                drivername="mysql+mysqlconnector",  # Use mysql-connector-python driver
                username=secret_dict['username'],
                password=secret_dict['password'],
                host=secret_dict['host'],
                port=secret_dict.get('port', 3306),
                database=secret_dict.get('dbname', 'dd340b_mysql_db')
            )
        else:
            print(f"Unknown secret format. Available keys: {list(secret_dict.keys())}")
            return None
            
        return _database_url_cache
    else:
        _database_url_cache = json.loads(response['SecretBinary'])
        return _database_url_cache

def get_engine():
    """
    Get or create the SQLAlchemy engine with optimized connection pooling.
    
    This function implements lazy initialization - the engine is only created
    when first needed, not at module import time. This significantly reduces
    Lambda cold start time for endpoints that don't use the database.
    
    Connection pooling settings are optimized for Lambda:
    - pool_size=5: Maintain up to 5 connections in the pool
    - max_overflow=10: Allow up to 10 additional connections beyond pool_size
    - pool_recycle=3600: Recycle connections after 1 hour to avoid stale connections
    - pool_pre_ping=True: Verify connections are alive before using them
    - connection_timeout=10: Timeout for initial connection (10 seconds)
    
    Returns:
        SQLAlchemy Engine instance
        
    Raises:
        DatabaseConnectionError: If unable to connect to database
        DatabaseConfigurationError: If database configuration is invalid
    """
    global _engine
    
    if _engine is None:
        print("Initializing database engine (lazy initialization)...")
        
        try:
            # Get database secret ARN from environment variable set by CDK cross-stack reference
            secret_arn = os.environ.get('DB_SECRET_ARN')
            if not secret_arn:
                raise DatabaseConfigurationError("DB_SECRET_ARN environment variable not set by CDK")
            
            print(f"Using database secret ARN from CDK: {secret_arn}")
            database_url = get_secret(secret_arn)
            
            if not database_url:
                raise DatabaseConnectionError("Failed to retrieve database URL from Secrets Manager")
            
            # Create engine with optimized connection pooling for Lambda
            _engine = create_engine(
                database_url,
                pool_size=5,              # Maintain 5 connections in pool
                max_overflow=10,          # Allow up to 10 additional connections
                pool_recycle=3600,        # Recycle connections after 1 hour
                pool_pre_ping=True,       # Verify connections before use
                connect_args={
                    'connection_timeout': 10  # Connection timeout (10 seconds)
                }
            )
            
            # Create tables if they don't exist (only on first engine creation)
            Base.metadata.create_all(_engine)
            
            print("Database engine initialized successfully")
            
        except (DatabaseConnectionError, DatabaseConfigurationError):
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            # Wrap any other exceptions in DatabaseConnectionError
            print(f"Unexpected error initializing database engine: {e}")
            raise DatabaseConnectionError(f"Failed to initialize database engine: {str(e)}")
    
    return _engine

@lru_cache(maxsize=1)  # Cache the engine instance for reuse across Lambda invocations
def get_sf_engine():

    secret_client = boto3.client('secretsmanager')
    secret_name = os.environ.get('SNOWFLAKE_SECRET_NAME',"f1ai-pwsa0001520")
    if not secret_name:
        raise DatabaseConfigurationError("SNOWFLAKE_SECRET_NAME environment variable not set by CDK")
    try:
        response = secret_client.get_secret_value(SecretId=secret_name)
        secret_json = json.loads(response["SecretString"])
        pem_string = secret_json.get("snow_pass")

        p_key = serialization.load_pem_private_key(
            pem_string.encode("utf-8"), password=None, backend=default_backend()
        )
        pk_bytes = p_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        sf_url = SnowflakeURL(
            user=os.environ.get('SF_USER'),
            account=os.environ.get('SF_ACCOUNT'),
            warehouse=os.environ.get('SF_WAREHOUSE'),
            database=os.environ.get('SF_DATABASE'),
            schema=os.environ.get('SF_SCHEMA'),
            role=os.environ.get('SF_ROLE'),
        )
        engine = create_engine(sf_url,
                               pool_size=5,
                               max_overflow=10,
                               pool_recycle=1800,      # 30 min (Snowflake idle timeout can be shorter)
                               pool_pre_ping=True,
                               pool_timeout=30,
                               connect_args={
                                    'private_key': pk_bytes,
                                    }
                                )

        return engine
    except Exception as e:
        print(f"Unexpected error initializing Snowflake engine: {e}")
        raise DatabaseConnectionError(f"Failed to initialize Snowflake engine: {str(e)}")
    

  
def get_sf_session():
    """
    Get a new Snowflake database session.
    
    This function creates a new session using the lazily-initialized Snowflake engine.
    Sessions should be closed after use (use try/finally or context manager).
    
    Returns:
        SQLAlchemy Session instance
    """
    
    engine = get_sf_engine()
    session = sessionmaker(bind=engine)
    
    return session()


def get_session():
    """
    Get a new database session.
    
    This function creates a new session using the lazily-initialized engine.
    Sessions should be closed after use (use try/finally or context manager).
    
    Returns:
        SQLAlchemy Session instance
    """
    global _Session
    
    if _Session is None:
        engine = get_engine()
        _Session = sessionmaker(bind=engine)
    
    return _Session()


def execute_with_error_handling(query_func, tile_name, *args, **kwargs):
    """
    Execute a database query function with comprehensive error handling.
    
    This wrapper function provides consistent error handling for all database operations:
    - Catches connection errors and returns standardized error responses
    - Handles query timeouts with appropriate error messages
    - Ensures database sessions are properly closed
    - Logs errors for monitoring and debugging
    
    Args:
        query_func: The database query function to execute
        tile_name: Name of the tile for error reporting
        *args: Positional arguments to pass to query_func
        **kwargs: Keyword arguments to pass to query_func
    
    Returns:
        Query result on success, or error dictionary on failure
        
    Error Response Format:
        {
            "error": "Error type",
            "message": "Detailed error message",
            "tileName": "tile-name"
        }
    """
    session = None
    try:
        # Execute the query function
        result = query_func(*args, **kwargs)
        return result
        
    except DatabaseConnectionError as e:
        print(f"Database connection error for {tile_name}: {e}")
        return {
            "error": "Database connection failed",
            "message": "Unable to connect to database. Please try again later.",
            "tileName": tile_name
        }
        
    except DatabaseTimeoutError as e:
        print(f"Database timeout error for {tile_name}: {e}")
        return {
            "error": "Database query timeout",
            "message": "The database query took too long to complete. Please try again or contact support.",
            "tileName": tile_name
        }
        
    except DatabaseQueryError as e:
        print(f"Database query error for {tile_name}: {e}")
        return {
            "error": "Database query failed",
            "message": f"Failed to execute database query: {str(e)}",
            "tileName": tile_name
        }
        
    except Exception as e:
        print(f"Unexpected error for {tile_name}: {e}")
        return {
            "error": "Internal server error",
            "message": f"An unexpected error occurred: {str(e)}",
            "tileName": tile_name
        }
    finally:
        # Ensure session is closed if it was created
        if session:
            try:
                session.close()
            except Exception as e:
                print(f"Error closing session for {tile_name}: {e}")


def _validate_date_param(date_value: str, param_name: str) -> None:
    """Validate a single date parameter."""
    try:
        datetime.strptime(date_value, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Invalid '{param_name}' date format: {date_value}. Expected YYYY-MM-DD")


def _validate_date_range(from_date: str, to_date: str) -> None:
    """Validate that from_date is not after to_date."""
    from_dt = datetime.strptime(from_date, "%Y-%m-%d")
    to_dt = datetime.strptime(to_date, "%Y-%m-%d")
    if from_dt > to_dt:
        raise ValueError(f"'from' date ({from_date}) cannot be after 'to' date ({to_date})")


def _validate_limit_param(limit) -> None:
    """Validate the limit parameter."""
    try:
        limit_int = int(limit)
        if limit_int <= 0:
            raise ValueError(f"Invalid limit value: {limit}. Expected positive integer")
    except (ValueError, TypeError):
        raise ValueError(f"Invalid limit value: {limit}. Expected positive integer")


def validate_query_parameters_db(from_date=None, to_date=None, segment=None, limit=None):
    """
    Validate common database query parameters.

    Args:
        from_date: Start date in YYYY-MM-DD format (optional)
        to_date: End date in YYYY-MM-DD format (optional)
        segment: Segment filter - "340B" or "non-340B" (optional)
        limit: Maximum number of results (optional)

    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if all parameters are valid, False otherwise
        - error_message: Empty string if valid, error description if invalid

    Raises:
        ValueError: If parameters are invalid
    """
    if from_date:
        _validate_date_param(from_date, 'from')

    if to_date:
        _validate_date_param(to_date, 'to')

    if from_date and to_date:
        _validate_date_range(from_date, to_date)

    if segment and segment not in ["340B", "non-340B"]:
        raise ValueError(f"Invalid segment value: {segment}. Expected '340B' or 'non-340B'")

    if limit is not None:
        _validate_limit_param(limit)

    return True, ""

def update_status_by_id(anomaly_340bid: str, anomaly_id: int, anomaly_status: str) -> str:
    """
    Updates Anomaly_Status (and Anomaly_LastModifiedDate) for a single row by Anomaly_ID & Anomaly_340BID.
    Returns the number of rows updated (0 or 1).
    """
    with get_session() as session:
        try:
            rows = (
                session.query(AnomalyScore)
                .filter(AnomalyScore.Anomaly_ID == anomaly_id, AnomalyScore.Anomaly_340BID == anomaly_340bid)
                .update(
                    {
                        AnomalyScore.Anomaly_Status: anomaly_status,
                        AnomalyScore.Anomaly_LastModifiedDate: datetime.now(),
                    },
                    synchronize_session=False,  # efficient for direct updates
                )
            )
            session.commit()
            if rows == 1:
                return "status_updated"
            elif rows == 0:
                return "data_not_found"
            else:
                return "more_than_one_row_found"
        except Exception:
            session.rollback()
            return "server_error"

def update_rt_status_by_id(rt_id: int, anomaly_id: int, rt_status: str) -> str:
    update_stmt = text("""
        UPDATE 340B_RiskTheories
        SET
            Risk_Theory_Status = :rt_status,
            Risk_Theory_ModifiedDate = NOW()
        WHERE
            Risk_Theroy_ID = :rt_id
            AND Risk_Theory_AnomalyID = :anomaly_id
    """)

    with get_session() as session:
        try:
            result = session.execute(
                update_stmt,
                {
                    "rt_status": rt_status,
                    "rt_id": rt_id,
                    "anomaly_id": anomaly_id
                }
            )
            session.commit()

            if result.rowcount == 0:
                return "not_found"

            return "success"
        except Exception:
            session.rollback()
            return "server_error"

def to_camel_case(s):
    s = re.sub(r'[^a-zA-Z0-9]', ' ', s)  # replace non-alphanumeric with space
    parts = s.strip().split()
    return parts[0].lower() + ''.join(word.capitalize() for word in parts[1:])

def calculate_percentage_change(current, previous, period="month"):
    """
    Calculate percentage change returning formatted string values with proper prefixes.
    
    Args:
        current: Current period value (numeric)
        previous: Previous period value (numeric)
        period: Time period for comparison (default: "month", unused but kept for compatibility)
    
    Returns:
        String percentage change with proper prefixes or "N/A" for error cases:
        - Positive values with plus sign (e.g., "+15" for 15% increase)
        - Negative values with minus sign (e.g., "-8" for 8% decrease)
        - "0" for no change (no prefix needed)
        - "N/A" for division by zero, null values, or calculation errors
    """
    try:
        # Handle None/null previous values
        if previous is None:
            return "N/A"
        
        # Handle division by zero cases
        if previous == 0:
            return "N/A"
        
        # Handle None current values (treat as 0 for calculation)
        if current is None:
            current = 0
        
        # Calculate percentage change: ((current - previous) / previous) * 100
        percentage = ((current - previous) / previous) * 100
        
        # Check for infinity or very large values that can't be converted to integer
        # Use a more reasonable range for percentage values
        if not (-1e9 <= percentage <= 1e9):
            return "N/A"
        
        # Round to nearest integer (proper rounding logic for decimal percentages)
        rounded_integer = round(percentage)
        
        # Return formatted string with proper prefixes
        if rounded_integer > 0:
            return f"+{rounded_integer}"
        elif rounded_integer < 0:
            return str(rounded_integer)  # Already has minus sign
        else:
            return "0"  # No prefix for zero change
        
    except Exception as e:
        print(f"Error calculating percentage change (current={current}, previous={previous}): {e}")
        return "N/A"

def get_previous_month(year, month):
    """
    Calculate the previous calendar month with year rollover handling.
    
    Args:
        year (int): Current year
        month (int): Current month (1-12)
    
    Returns:
        tuple: (previous_year, previous_month) as integers
    
    Examples:
        >>> get_previous_month(2025, 3)
        (2025, 2)
        >>> get_previous_month(2025, 1)
        (2024, 12)
    """
    try:
        if month == 1:
            # January rolls back to December of previous year
            return (year - 1, 12)
        else:
            # All other months just decrement
            return (year, month - 1)
    except Exception as e:
        print(f"Error calculating previous month (year={year}, month={month}): {e}")
        # Return None to signal error - caller should handle this
        return None

# Action status constants
ACTION_STATUS_RESOLVED_AFTER_LETTER = "Resolved (after letter)"
ACTION_STATUS_LETTER_SENT = "Letter Sent"
ACTION_STATUS_OPEN_UNREAD = "Open (Unread)"
ACTION_STATUS_UNDER_INVESTIGATION = "Under Investigation"
ACTION_STATUS_CLOSED = "Closed"
ACTION_STATUS_FALSE_POSITIVE = "False Positive"
ACTION_STATUS_UNDER_HRSA_AUDIT = "Under HRSA Audit"
ACTION_STATUS_UNDER_INTERNAL_AUDIT = "Under Internal Audit"


def generate_action_status(linkage_score):
    """
    Generate a valid action status based on linkage score.

    Args:
        linkage_score: Linkage score percentage (0-100)

    Returns:
        str: One of the valid action status values
    """
    import random

    # Generate action based on linkage score for more realistic distribution
    if linkage_score >= 80:
        # High linkage scores more likely to have active actions
        return secrets.choice([ACTION_STATUS_LETTER_SENT, ACTION_STATUS_UNDER_INVESTIGATION, ACTION_STATUS_UNDER_HRSA_AUDIT])
    elif linkage_score >= 60:
        # Medium linkage scores mixed actions
        return secrets.choice([ACTION_STATUS_OPEN_UNREAD, ACTION_STATUS_LETTER_SENT, ACTION_STATUS_UNDER_INVESTIGATION, ACTION_STATUS_RESOLVED_AFTER_LETTER])
    else:
        # Lower linkage scores more likely to be closed or false positives
        return secrets.choice([ACTION_STATUS_CLOSED, ACTION_STATUS_FALSE_POSITIVE, ACTION_STATUS_RESOLVED_AFTER_LETTER, ACTION_STATUS_OPEN_UNREAD])