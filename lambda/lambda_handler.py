# ============================================================================
# Module-Level Imports (Lightweight - Always Loaded)
# ============================================================================
# These imports are loaded on every Lambda cold start, so we keep only
# the essential lightweight dependencies here.

from functools import lru_cache

from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.event_handler import APIGatewayRestResolver, CORSConfig
from aws_lambda_powertools.event_handler.api_gateway import Response
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext
from aws_lambda_powertools.utilities.data_classes import APIGatewayProxyEvent
from response_handler import response_handler

# Standard library and lightweight AWS SDK imports
import boto3
from botocore.config import Config
import os
import json
import base64
import re
import io
import uuid
from datetime import datetime
from dateutil.relativedelta import relativedelta
from sqlalchemy import text
from datetime import timedelta
from utils.DbUtil import get_session, update_status_by_id, update_rt_status_by_id, get_sf_session, calculate_percentage_change
from utils.utils_helper import sanitize_filter_value, build_days_open_filter, build_in_clause_filter
from utils.utils_helper import create_error_response, validate_optional_param
from utils.query_templates import (PowerBIReports, OverviewSummaryKPI, OverviewPageCharts, AllAnomaliesSummaryKPI, 
                                   AllAnomaliesPageCharts, AllAccountsSummaryKPI, AccountDetailsKPI, PharmacyDetailsKPI,
                                   AccountDetailsCharts, AnomalyDetailsKPI,PurchaseDispenseExp)

s3_client = boto3.client(
    's3',
    config=Config(signature_version="s3v4"),
)

metrics = Metrics(namespace="340B")
logger = Logger()
tracer = Tracer()
cors_config = CORSConfig(allow_origin="*")
app = APIGatewayRestResolver(cors=cors_config)

# ---------------- Constants ----------------
ALLOWED_HEADERS = "Content-Type,Authorization"
ALLOWED_METHODS = "OPTIONS,GET,POST,PUT,PATCH,DELETE,HEAD"
ALLOWED_ORIGIN = "*"
ANOMALY_STR_DATE_FORMAT = "%m/%d/%Y"
AWS_REGION="us-east-1"
CONNECTION_FAILED = "Database connection failed"
DISP_LABEL_340B = "340B Dispense Quantity"
DISP_LABEL_NON_340B = "Non 340B Dispense Quantity"
DISPENSE_QUANTITY = "Dispense Quantity"
EITHER_340BID_OR_PHARMACYID_REQUIRED = "Either 340bId or pharmacyId must be provided"
ERROR_CONNECTION = "Unable to connect to database. Please try again later."
ERROR_DOES_NOT_EXIST = "doesn't exist"
ERROR_UNKNOWN_TABLE = "unknown table"
INTERNAL_SERVER_ERROR = "Internal server error"
INVALID_PARAMS = "Invalid parameters"
INVALID_TIME_PERIOD = "Invalid time period"
LETTER_SENT = "Letter Sent"
MISSING_REQUIRED_PARAMETER = "Missing required parameter"
NO_DATA_AVAILABLE = "No data available"
NO_DATA_AVAILABLE_FOR_SPECIFIED_PARAMETERS = "No data available for the specified parameters"
NO_DATA_FOUND = "No data found"
PUR_LABEL_340B = "340B Purchase Quantity"
PUR_LABEL_NON_340B = "Non 340B Purchase Quantity"
PURCHASE_QUANTITY = "Purchase Quantity"
THE_VIEW_RETURNED_NO_DATA = "The view returned no data"
UPLOAD_BUCKET_NAME = os.getenv("DD340B_BUCKET_NAME", "default-340b-bucket") # bucket name fetched from cdk.json
UPLOAD_URL_EXPIRATION = 120 # 2 minutes expiration for presigned url
VIEW_NOT_FOUND = "View not found"


@lru_cache(maxsize=1)
def get_max_timeperiod():

    session = None

    try:
        session = get_session()
        query = text("""
        SELECT
            max_date,
            max_quarter,
            max_quarter_date,
            max_half_year,
            max_half_year_date,
            max_complete_year,
            max_complete_year_date
        FROM vwMaxTimePeriod
        """)
        result = session.execute(query).fetchone()
        if result:
            return {
                "max_date": result.max_date.strftime("%Y-%m-%d") if result.max_date else None,
                "max_quarter": result.max_quarter,
                "max_quarter_date": result.max_quarter_date.strftime("%Y-%m-%d") if result.max_quarter_date else None,
                "max_half_year": result.max_half_year,
                "max_half_year_date": result.max_half_year_date.strftime("%Y-%m-%d") if result.max_half_year_date else None,
                "max_complete_year": result.max_complete_year,
                "max_complete_year_date": result.max_complete_year_date.strftime("%Y-%m-%d") if result.max_complete_year_date else None
            }
        else:
            return None
    except Exception as e:
        logger.error(f"Error fetching max time period: {e}")
        return None
    finally:
        if session:
            session.close()

MAX_TIME_PERIOD = get_max_timeperiod()

@lru_cache(maxsize=1)
def get_anomaly_risk_status():

    session = get_session()
    result = {}
    try:
        result_anomaly_status_lookup = session.execute(text("SELECT DISTINCT `label`,`value` FROM `vwAnomalyStatus`")).fetchall()
        anomaly_status_lookup = [{"label": row.label, "value": str(row.value).upper()} for row in result_anomaly_status_lookup]
    except Exception as e:
        logger.error(f"Error fetching anomaly status lookup data: {e}")
        anomaly_status_lookup = []
    
    try:
        result_risk_status_lookup = session.execute(text("SELECT DISTINCT `label`,`value` FROM `vwRiskTheoryStatus`")).fetchall()
        risk_status_lookup = [{"label": row.label, "value": str(row.value).upper()} for row in result_risk_status_lookup]
    except Exception as e:
        logger.error(f"Error fetching risk status lookup data: {e}")
        risk_status_lookup = []
    
    result["anomalyStatusLookup"] = anomaly_status_lookup
    result["riskTheoryStatusLookup"] = risk_status_lookup

    return result

ALLOWED_STATUSES = get_anomaly_risk_status()

@app.get("/api/v1/healthcheck")
@tracer.capture_method
def insert_ml():
    print("** inside healthcheck **")
    return {"status": "success", "message": "Healthcheck OK!!"}

@app.get("/api/v1/lookupdata/cecp")
@tracer.capture_method
def fetch_cecp_lookupdata():
    response = {}
    session = None
    print("fetch_cecp_lookupdata called") 

    try:  
        # Import database utilities for querying
        from utils.DbUtil import get_session
        from sqlalchemy import text
        
        # Query the view directly
        session = get_session()

        ce_result = session.execute(text("SELECT DISTINCT p.340BID as AccountID, c.Entity_Name FROM `340B_340BPurchases` p JOIN `340B_CoveredEntities` c ON p.340BID = c.340B_ID")).fetchall()
        
        ce_list = []
        if ce_result:
            for ce_row in ce_result:
                ce_list.append({
                "account_id": ce_row.AccountID,
                "account_name": ce_row.Entity_Name
            })  

        cp_result = session.execute(text("SELECT DISTINCT p.PharmacyID, c.Pharmacy_Name FROM `340B_Non340BPurchases` p JOIN `340B_ContractPharmacies` c ON p.PharmacyID = c.Pharmacy_ID")).fetchall()
        
        cp_list = []
        if cp_result:
            for cp_row in cp_result:
                cp_list.append({
                "pharmacy_id": cp_row.PharmacyID,
                "pharmacy_name": cp_row.Pharmacy_Name
            })  

        response["purchase-dispense-picklist"] = {
            "covered_entities": ce_list,
            "contract_pharmacies": cp_list
        }
        print(f"** response after fetching cecp lookup data {response}")
        
        return response
        
    except Exception as e:
        logger.error(f"Error fetching purchase-dispense-picklist data: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e)
        }
    finally:
        if session:
            session.close()

@app.get("/api/v1/lookupdata")
@tracer.capture_method
def fetch_lookupdata():

    session = None
    brands = []
    states = []
    entity_types = []
    anomaly_status_lookup = []
    risk_status_lookup = []
    try:
        session = get_session()
        # Dynamic brands from the database
        try:
            result = session.execute(text("SELECT DISTINCT `Brand` FROM `340B_ProcessedData`")).fetchall()
            brands = [{"label": str(row.Brand).capitalize(), "value": row.Brand} for row in result if row.Brand]
        except Exception as e:
            logger.error(f"Error fetching brands lookup data: {e}")
            brands = []

        try:
            result_states = session.execute(text("SELECT DISTINCT `State` FROM `340B_340BPurchases`")).fetchall()
            states = [{"label": str(row.State).upper(), "value": str(row.State).upper()} for row in result_states if row.State]
        except Exception as e:
            logger.error(f"Error fetching states lookup data: {e}")
            states = []

        try:
            result_entity_types = session.execute(text("SELECT DISTINCT `Entity_Type` FROM `vwAnomalousTransactions`")).fetchall()
            entity_types = [{"label": str(row.Entity_Type).upper(), "value": str(row.Entity_Type).upper()} for row in result_entity_types if row.Entity_Type]
        except Exception as e:
            logger.error(f"Error fetching entity_types lookup data: {e}")
            entity_types = []

        anomaly_status_lookup = ALLOWED_STATUSES["anomalyStatusLookup"]

        risk_status_lookup = ALLOWED_STATUSES["riskTheoryStatusLookup"]

    except Exception as e:
        logger.error(f"Error creating session for lookup data: {e}")
    
    return {
        "brands": brands,
        "status": [
            {"label": "Open", "value": "Open"},
            {"label": "Closed", "value": "Closed"},
            {"label": "Pending", "value": "Pending"},
        ],
        "anomalyStatusLookup": anomaly_status_lookup,
        "customerTypes": entity_types,
        "riskTheoryStatusLookup": risk_status_lookup,
        "regions": [
            {"label": "North", "value": "North"},
            {"label": "South", "value": "South"},
            {"label": "East", "value": "East"},
            {"label": "West", "value": "West"},
        ],
        "states": states,
        "anomalyScore": [
            {"label": "<50%", "value": "<50%"},
            {"label": "50-59%", "value": "50-59%"},
            {"label": "60-69%", "value": "60-69%"},
            {"label": "70-79%", "value": "70-79%"},
            {"label": "80-89%", "value": "80-89%"},
        ],
        "parentAccount": [
            {"label": "Parent Account A", "value": "Parent Account A"},
            {"label": "Parent Account B", "value": "Parent Account B"},
            {"label": "Parent Account C", "value": "Parent Account C"},
        ],
        "340bId": [
            {"label": "340B-10001", "value": "340B-10001"},
            {"label": "340B-10002", "value": "340B-10002"},
            {"label": "340B-10003", "value": "340B-10003"},
        ],
    }

@app.put("/api/v1/account/<account_id>/anomaly/<anomaly_id>/risktheory/<risk_theory_id>")
@tracer.capture_method
def update_risk_theory(account_id: str, anomaly_id: int, risk_theory_id: int):
    print("** inside update_risk_theory")
    body = app.current_event.json_body
    risk_theory_status = body.get("riskTheoryStatus")
    
    print(f"** risk_theory_id {risk_theory_id} anomaly_id {anomaly_id} risk_theory_status {risk_theory_status} ") 

    if not is_valid_risk_theory_status(risk_theory_status):
        return {
            "status": "error",
            "message": f"Invalid risk theory status: {risk_theory_status}"
        }
    message = update_rt_status_by_id(risk_theory_id, anomaly_id, risk_theory_status)
    return {"status": "success", "message": message}


@app.put("/api/v1/account/<account_id>/anomaly/<anomaly_id>")
@tracer.capture_method
def update_anomaly(account_id: str, anomaly_id: int):
    print("** inside update_anomaly")
    body = app.current_event.json_body
    anomaly_status = body.get("anomalyStatus")
    
    print(f"** account_id {account_id} anomaly_id {anomaly_id} anomaly_status {anomaly_status} ") 

    if not is_valid_status(anomaly_status):
        return {
            "status": "error",
            "message": f"Invalid anomaly status: {anomaly_status}"
        }
    message = update_status_by_id(account_id, anomaly_id, anomaly_status)
    return {"status": "success", "message": message}

def is_valid_status(status: str) -> bool:
    return status in [item["value"] for item in ALLOWED_STATUSES["anomalyStatusLookup"]]

def is_valid_risk_theory_status(status: str) -> bool:
    return status in [item["value"] for item in ALLOWED_STATUSES["riskTheoryStatusLookup"]]

def ensure_uuid(value: object) -> str:
    """
    Return a UUID string if `value` is None, empty, or only whitespace;
    otherwise, return the original string value.
    """
    if value is None:
        return str(uuid.uuid4())
    if isinstance(value, str):
        if value.strip() == "":
            return str(uuid.uuid4())
        return value
    # If it's not a string (e.g., number/obj), coerce to str but don't overwrite
    return str(value)

@app.post("/api/v1/chat")
@tracer.capture_method
def chatbot_interact():
    print("** inside chatbot_interact")
    body = app.current_event.json_body
    message = body.get("question", "")
    print(f"** question {message}")
    br_agent_client = boto3.client(
        "bedrock-agent-runtime",
        region_name=AWS_REGION,
    )
    ssm_client = boto3.client("ssm", region_name=AWS_REGION)
    try:
        # Retrieve agent_id and agent_alias_id from SSM Parameter Store
        agent_id = ssm_client.get_parameter(Name='/bedrock/agent_id')['Parameter']['Value']
        agent_alias_id = ssm_client.get_parameter(Name='/bedrock/agent_alias_id')['Parameter']['Value']
        session_id = ensure_uuid(body.get("session_id"))
        memory_id  = ensure_uuid(body.get("memory_id"))
        print(f"** agent_id: {agent_id} agent_alias_id: {agent_alias_id}")
        print(f"** session_id: {session_id} memory_id: {memory_id}")
        response = br_agent_client.invoke_agent(
            agentId=agent_id,
            agentAliasId=agent_alias_id,
            sessionId = session_id,
            memoryId = memory_id,
            enableTrace=True,
            inputText=message,
            streamingConfigurations={
                "streamFinalResponse": True  # Set to True for streaming response
            }
        )
        completion = ""
        for event in response.get("completion", []):
            if 'chunk' in event:
                chunk = event["chunk"]
                completion += chunk["bytes"].decode()
            if 'trace' in event:
                trace_event = event.get("trace")
                trace = trace_event['trace']
                for key, value in trace.items():
                    print("%s: %s", key, value)
        print(f"** Agent response: {completion}")
        print(f"** session_id: {session_id}, memory_id: {memory_id}")
        return {
            "status": "success",
            "answer": completion,
            "session_id": session_id,
            "memory_id": memory_id
        }
    except Exception as e:
        print(f"ERROR: {e}")
        return {
            "status": "success",
            "answer": "The assistant is temporarily unavailable. Please try again later.",
            "session_id": None,
            "memory_id": None,
        }

# Utility function to fetch anomaly details, can be used by multiple endpoints within this module
def _fetch_anomaly_details(session, anomaly_id: int):
    """
    Internal method to fetch anomaly details from the database.
    This method is not exposed as an API endpoint and can be used by other functions within this module.
    """
    result = {}

    try:
        anomaly_query = text(AnomalyDetailsKPI.ANOMALIES_BY_SCORE.value)
        result = session.execute(anomaly_query, {"anomaly_id": anomaly_id})
        anomaly_details = result.fetchone()

        if not anomaly_details:
            return {
                "error": "Anomaly details not found",
                "message": f"Anomaly details not found for the anomaly id {anomaly_id}",
            }
        
        result = {
        "anomalyId": anomaly_details.Anomaly_ID,
        "accountId": anomaly_details.Anomaly_340BID,
        "pharmacyId": anomaly_details.Pharmacy_ID,
        "anomalyDate": anomaly_details.Anomaly_Date.strftime(ANOMALY_STR_DATE_FORMAT),
        "brand": anomaly_details.Anomaly_Brand,
        "daysOpen": f"{(datetime.now().date() - anomaly_details.Anomaly_Date).days} Days",
        "anomalyDetectedBy": anomaly_details.Anomaly_Detected_By,
        "anomalySource": anomaly_details.Anomaly_Source,
        "action": anomaly_details.Anomaly_Status,
        "anomalyWAC": float(anomaly_details.Anomaly_WAC),
        "anomalyUnits": int(anomaly_details.Anomaly_Units),
        "anomalyChargeBack": float(anomaly_details.Anomaly_ChargeBack),
        "anomalyLinkageScore": float(anomaly_details.Anomaly_LinkageScore)
        }

        return result
    except Exception as e:
        logger.error(f"Error fetching anomaly details: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e)
        }

def _fetch_account_details_for_anomaly(session, account_id: str):
    """
    Internal method to fetch account details for a given anomaly from the database.
    This method is not exposed as an API endpoint and can be used by other functions within this module.
    """

    try:
        account_query = text(AnomalyDetailsKPI.ACCOUNT_HEADER.value)
        account_result = session.execute(account_query, {"account_id": account_id.upper()})
        account_details = account_result.fetchone()

        if account_details:
           logger.info(f"Account details found for account_id {account_id}: accountName={account_details.accountName}")
           return {
            "anomalyEntityName": account_details.accountName or "Unknown Entity",
            "accountAddress": account_details.address or "Unknown Address"
        }
        else:
            logger.info(f"No account details found for account_id {account_id}. Returning default values.")
            return {
            "anomalyEntityName": "Unknown Entity",
            "accountAddress": "Unknown Address"
        }

    except Exception as e:
        logger.error(f"Error fetching account details for anomaly: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e)
        }

def _fetch_pharmacy_details_for_anomaly(session, pharmacy_id: str):
    """
    Internal method to fetch pharmacy details for a given anomaly from the database.
    This method is not exposed as an API endpoint and can be used by other functions within this module.
    """

    try:
        pharmacy_query = text(AnomalyDetailsKPI.PHARMACY_HEADER.value)
        pharmacy_result = session.execute(pharmacy_query, {"pharmacy_id": pharmacy_id.upper()})
        pharmacy_details = pharmacy_result.fetchone()

        if pharmacy_details:
            logger.info(f"Pharmacy details found for pharmacy_id {pharmacy_id}: accountName={pharmacy_details.accountName}")
            return {
                "pharmacyName": pharmacy_details.accountName or "Unknown Pharmacy",
                "pharmacyAddress": pharmacy_details.address or "Unknown Pharmacy Address"
            }
        else:
            logger.info(f"No pharmacy details found for pharmacy_id {pharmacy_id}. Returning default values.")
            return {
                "pharmacyName": "Unknown Pharmacy",
                "pharmacyAddress": "Unknown Pharmacy Address"
            }

    except Exception as e:
        logger.error(f"Error fetching pharmacy details for anomaly: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e)
        }
    
def _fetch_anomaly_timeline_data(session, anomaly_date: datetime, account_id: str, pharmacy_id: str):
    """
    Internal method to fetch anomaly timeline data for a given anomaly from the database.
    This method is not exposed as an API endpoint and can be used by other functions within this module.
    """

    try:
        query = text(AnomalyDetailsKPI.ANOMALY_TIMELINE.value)

        result = session.execute(query,
        {
            "anomaly_date": anomaly_date,
            "id_340b": account_id,
            "pharmacy_id": pharmacy_id
        })

        timeline_data = result.fetchall()
        # Extract data from query results
        categories = []
        dispense_data_340b = []
        purchase_data_340b = []
        dispense_data_non340b = []
        purchase_data_non340b = []

        for row in timeline_data:
            categories.append(str(row.category))
            dispense_data_340b.append({"category": str(row.category), "dispense_quantity": int(row.dispense_quantity or 0)})
            purchase_data_340b.append({"category": str(row.category), "purchase_quantity": int(row.purchase_quantity or 0)})
            dispense_data_non340b.append({"category": str(row.category), "non_340b_dispense_quantity": int(row.non_340b_dispense_quantity or 0)})
            purchase_data_non340b.append({"category": str(row.category), "non_340b_purchase_quantity": int(row.non_340b_purchase_quantity or 0)})
        
        result = {"categories": categories,
                  "dispense_data_340b": dispense_data_340b,
                  "purchase_data_340b": purchase_data_340b,
                  "dispense_data_non340b": dispense_data_non340b,
                  "purchase_data_non340b": purchase_data_non340b}

        return result

    except Exception as e:
        logger.error(f"Error fetching anomaly timeline data: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e)
        }
    
def _fetch_purchase_dispense_by_account(session, account_id: str, brand: str):
    """
    Internal method to fetch purchase vs dispense quantity by account for a given anomaly from the database.
    This method is not exposed as an API endpoint and can be used by other functions within this module.
    """

    try:
        query = text(AnomalyDetailsKPI.PUR_DISP_BY_ACCOUNT.value)

        result = session.execute(query,
        {
            "account_id": account_id,
            "brand": brand
        })

        data = result.fetchall()
        purchase_dispense_by_account_list = []
        for row in data:
            purchase_dispense_by_account_list.append({
                "pharmacyName": row.pharmacyName,
                "address": row.address,
                "non340bPurchaseQty": int(row.non340bPurchaseQty or 0),
                "non340bDispenseQty": int(row.non340bDispenseQty or 0)
            })
        
        return purchase_dispense_by_account_list

    except Exception as e:
        logger.error(f"Error fetching purchase vs dispense by account data for account {account_id}: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e)
        }
    
def _fetch_purchase_dispense_by_pharmacy(session, pharmacy_id: str, brand: str):
    """
    Internal method to fetch purchase vs dispense quantity by pharmacy for a given anomaly from the database.
    This method is not exposed as an API endpoint and can be used by other functions within this module.
    """

    try:
        query = text(AnomalyDetailsKPI.PUR_DISP_BY_PHARMACY.value)

        result = session.execute(query,
        {
            "pharmacy_id": pharmacy_id,
            "brand": brand
        })

        data = result.fetchall()
        purchase_dispense_by_pharmacy_list = []
        for row in data:
            purchase_dispense_by_pharmacy_list.append({
                "accountName": row.accountName,
                "address": row.address,
                "340bPurchaseQty": int(row.purchaseQty or 0),
                "340bDispenseQty": int(row.dispenseQty or 0),
            })
        
        return purchase_dispense_by_pharmacy_list

    except Exception as e:
        logger.error(f"Error fetching purchase vs dispense by pharmacy data for pharmacy {pharmacy_id}: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e)
        }

def _fetch_risk_theory_for_anomaly(session, anomaly_id: int, anomaly_score: float):
    """
    Internal method to fetch risk theory data for a given anomaly from the database. anomaly_score is used to determine the correlation label for the risk theory data.
    """
    
    try:
        if anomaly_score is not None:
            if anomaly_score >= 90:
                correlation_label = 'High Correlation'
            elif anomaly_score >= 50:
                correlation_label = 'Medium Correlation'
            else:
                correlation_label = 'Low Correlation'
        else:
            correlation_label = 'Unknown Correlation' # Should not happen as anomaly_score is expected to be always present, but added for safety
        query = text(AnomalyDetailsKPI.RISK_THEORY.value)
        result = session.execute(query, {"anomaly_id": anomaly_id})
        risk_theory_data = result.fetchall()
        risk_theory_list = []
        for row in risk_theory_data:
            risk_theory_list.append({
                "description": row.Risk_Theory_Description,
                "status": row.Risk_Theory_Status,
                "riskTheoryId": row.Risk_Theory_ID,
                "correlationLabel": correlation_label,
                "confidence": anomaly_score
            })
        return risk_theory_list
    except Exception as e:
        logger.error(f"Error fetching risk theory data for anomaly_id {anomaly_id}: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e)
        }


def _fetch_purchase_dispense_picklist(session):

    """
    Internal method to fetch covered entities and contract pharmacies Ids from the database for purchase vs dispense explorer.
    """
    try:
        ce_result = session.execute(text("SELECT DISTINCT p.340BID as AccountID, c.Entity_Name FROM `340B_340BPurchases` p JOIN `340B_CoveredEntities` c ON p.340BID = c.340B_ID")).fetchall()
        
        ce_list = []
        if ce_result:
            for ce_row in ce_result:
                ce_list.append({
                "account_id": ce_row.AccountID,
                "account_name": ce_row.Entity_Name
            })  

        cp_result = session.execute(text("SELECT DISTINCT p.PharmacyID, c.Pharmacy_Name FROM `340B_Non340BPurchases` p JOIN `340B_ContractPharmacies` c ON p.PharmacyID = c.Pharmacy_ID")).fetchall()
        cp_list = []
        if cp_result:
            for cp_row in cp_result:
                cp_list.append({
                    "pharmacy_id": cp_row.PharmacyID,
                    "pharmacy_name": cp_row.Pharmacy_Name
                })
        return {"covered_entities": ce_list, "contract_pharmacies": cp_list}
    except Exception as e:
        logger.error(f"Error fetching purchase dispense picklist: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e)
        }

@app.get("/api/v1/account/<account_id>/anomaly/<anomaly_id>")
@tracer.capture_method
def get_anomaly_details(account_id: str, anomaly_id: int):
    logger.debug("Inside get_anomaly_details")
    logger.debug(f"account_id={account_id}, anomaly_id={anomaly_id}")
    response = {}
    session = None
    anomaly_id = int(anomaly_id)

    try:           

        if not account_id or anomaly_id <= 0:
            return {
                "error": MISSING_REQUIRED_PARAMETER,
                "message": "Invalid account_id or anomaly_id. account_id must be a non-empty string and anomaly_id must be a positive integer.",
                "tileName": "anomaly-details"
            }
        
        # Query the view directly
        session = get_session()
        anomaly_details = {}
        anomaly_details = _fetch_anomaly_details(session, anomaly_id)
        if anomaly_details and "error" not in anomaly_details:
            # Verify the anomaly belongs to the specified account
            if anomaly_details.get("accountId", "").upper() != account_id.upper():
                return {
                    "error": "Anomaly not found",
                    "message": f"Anomaly {anomaly_id} does not belong to account {account_id}",
                    "tileName": "anomaly-details"
                }
            account_details = _fetch_account_details_for_anomaly(session, account_id)
            anomaly_kpis = {"anomalyWac": anomaly_details.pop("anomalyWAC"),
                            "anomalyUnits": anomaly_details.pop("anomalyUnits"),
                            "anomalyChargeBack": anomaly_details.pop("anomalyChargeBack")}
            anomaly_linkage_score = anomaly_details.pop("anomalyLinkageScore")

            anomaly_details.update({
                "anomalyEntityName": account_details.get("anomalyEntityName"),
                "address": account_details.get("accountAddress")
            })
            response["anomaly-detail"] = anomaly_details
            pharmacy_details = _fetch_pharmacy_details_for_anomaly(session, str(anomaly_details.get("pharmacyId")).upper())

            response["pharmacy-details"] = [
                {
                    "pharmacyName": pharmacy_details.get("pharmacyName"),
                    "pharmacyAddress": pharmacy_details.get("pharmacyAddress"),
                }
            ]
            response["anomaly-kpis"] = {
                "daysActive": {"count": (datetime.now().date() - datetime.strptime(anomaly_details.get("anomalyDate"), ANOMALY_STR_DATE_FORMAT).date()).days, "compareToPrevious" : 0.0},#fix it later
                "duration": {"count": "1", "compareToPrevious" : 0.0},
                "riskExposure": {"count": float(anomaly_kpis.get("anomalyWac")), "compareToPrevious" : 0.0},
                "total340bVolume": {"count": int(anomaly_kpis.get("anomalyUnits")), "compareToPrevious" : 0.0}
            }
            response["anomalous-period"] = {
                "startDate": (datetime.strptime(anomaly_details.get("anomalyDate"), ANOMALY_STR_DATE_FORMAT) - timedelta(days=30)).strftime(ANOMALY_STR_DATE_FORMAT),
                "endDate": (datetime.strptime(anomaly_details.get("anomalyDate"), ANOMALY_STR_DATE_FORMAT) + timedelta(days=30)).strftime(ANOMALY_STR_DATE_FORMAT)
            }
            logger.debug(f"Response after anomaly-kpis: {response}")
            anomaly_timeline = _fetch_anomaly_timeline_data(session, datetime.strptime(anomaly_details.get("anomalyDate"), ANOMALY_STR_DATE_FORMAT), account_id, str(anomaly_details.get("pharmacyId")).upper())
            # Build response structure matching the expected format
            response["anomaly-timeline"] = {
                "categories": anomaly_timeline.get("categories", []),
                "series": [
                    {
                        "name": DISP_LABEL_340B,
                        "data": anomaly_timeline.get("dispense_data_340b", []),
                        "type": "line",
                        "yAxis": 0
                    },
                    {
                        "name": PUR_LABEL_340B,
                        "data": anomaly_timeline.get("purchase_data_340b", []),
                        "type": "line",
                        "yAxis": 1
                    },
                    {
                        "name": DISP_LABEL_NON_340B,
                        "data": anomaly_timeline.get("dispense_data_non340b", []),
                        "type": "line",
                        "yAxis": 0
                    },
                    {
                        "name": PUR_LABEL_NON_340B,
                        "data": anomaly_timeline.get("purchase_data_non340b", []),
                        "type": "line",
                        "yAxis": 1
                    }
                ]
            }
            logger.debug(f"Response after anomaly-timeline: {response}")
                
            response["purchase-dispense-by-account-list"] = _fetch_purchase_dispense_by_account(session, account_id, anomaly_details.get("brand"))
            logger.debug(f"Response after purchase-dispense-by-account-list: {response}")
                
            response["purchase-dispense-by-pharmacy-list"] = _fetch_purchase_dispense_by_pharmacy(session, str(anomaly_details.get("pharmacyId")).upper(), anomaly_details.get("brand"))
            logger.debug(f"Response after purchase-dispense-by-pharmacy-list: {response}")

            response["riskTheory"] = _fetch_risk_theory_for_anomaly(session, anomaly_id, anomaly_linkage_score)
            logger.debug(f"Response after riskTheory: {response}")

            response["purchase-dispense-picklist"] = _fetch_purchase_dispense_picklist(session)
            logger.debug(f"Response after purchase-dispense-picklist: {response}")
        else:
            # Return the error from _fetch_anomaly_details, or a generic error if empty
            return anomaly_details if anomaly_details else {
                "error": "Anomaly not found",
                "message": f"No anomaly found with id {anomaly_id}"
            }
        
        return response
        
    except Exception as e:
        logger.error(f"Error fetching dispense vs purchase volume data: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e)
        }
    finally:
        if session:
            session.close()

@app.get("/api/v1/account/<account_id>/pharmacy/<pharmacy_id>/purchase-dispense")
@tracer.capture_method
def get_purchase_dispense_timeline(account_id: str, pharmacy_id: int):
    print("** inside get_purchase_dispense_timeline")
    
    print(f"** account_id {account_id}  pharmacy_id {pharmacy_id}") 
    print(f"** get_purchase_dispense_timeline query params {app.current_event.query_string_parameters}")
    
    # Get query string parameters
    query_params = app.current_event.query_string_parameters or {}
    filter_string = ""
    valid_filter_column_map = {
        "brands": "Brand",
        "states": "State"
    }
                
    response = {}
    session = None
    pharmacy_id = int(pharmacy_id)

    try:           

        if not account_id or pharmacy_id <= 0:
            return {
                "error": MISSING_REQUIRED_PARAMETER,
                "message": "Invalid account_id or pharmacy_id. account_id must be a non-empty string and pharmacy_id must be a positive integer.",
                "tileName": "purchase-dispense-timeline"
            }
 
        if query_params:
            filter_string = generate_global_filters_from_query_params(query_params, valid_filter_column_map)
        
        # Query the view directly
        session = get_session()
        raw_query = PurchaseDispenseExp.PUR_DISP_EXP.value
        query = text(raw_query.format(query_params=filter_string))

        result = session.execute(query,
        {
            "id_340b": account_id,
            "pharmacy_id": pharmacy_id,
            "max_date": get_date_for_time_period("monthly")
        })
        
        rows = result.fetchall()
        
        # Extract data from query results
        categories = []
        dispense_data_340b = []
        purchase_data_340b = []
        dispense_data_non340b = []
        purchase_data_non340b = []
        
        for row in rows:
            categories.append(str(row.category))
            dispense_data_340b.append(
                {
                    "category": str(row.category),
                    "dispense_quantity": int(row.ce_dispense_qty) if row.ce_dispense_qty else 0
                }
            )
            purchase_data_340b.append(
                {
                    "category": str(row.category),
                    "purchase_quantity": int(row.ce_purchase_qty) if row.ce_purchase_qty else 0
                }
            )
            dispense_data_non340b.append(
                {
                    "category": str(row.category),
                    "non_340b_dispense_quantity": int(row.cp_dispense_qty) if row.cp_dispense_qty else 0
                }
            )
            purchase_data_non340b.append(
                {
                    "category": str(row.category),
                    "non_340b_purchase_quantity": int(row.cp_purchase_qty) if row.cp_purchase_qty else 0
                }
            )
        
        # Build response structure matching the expected format
        response["purchase-dispense-timeline"] = {
            "categories": categories,
            "series": [
                {
                    "name": DISP_LABEL_340B,
                    "data": dispense_data_340b,
                    "type": "line",
                    "yAxis": 0
                },
                {
                    "name": PUR_LABEL_340B,
                    "data": purchase_data_340b,
                    "type": "line",
                    "yAxis": 1
                },
                {
                    "name": DISP_LABEL_NON_340B,
                    "data": dispense_data_non340b,
                    "type": "line",
                    "yAxis": 0
                },
                {
                    "name": PUR_LABEL_NON_340B,
                    "data": purchase_data_non340b,
                    "type": "line",
                    "yAxis": 1
                }
            ]
        }
        print(f"** response after anomaly-timeline {response}")
        
        return response
        
    except Exception as e:
        logger.error(f"Error fetching dispense vs purchase volume data: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e)
        }
    finally:
        if session:
            session.close()

# No prefix added, takes from root of the S3 bucket
def _get_bucket_and_key_prefix():
    # Single, default upload type: kb-sync
    return UPLOAD_BUCKET_NAME, ""


# Handle unstructured file uploads, returns presigned url from S3 to upload directly
@app.post("/api/v1/kb-sync/get-upload-url")
@tracer.capture_method
def generate_upload_presigned_url():
    print("Inside generate_upload_presigned_url for upload_type=kb-sync")

    body = app.current_event.json_body or {}
    file_name = body.get("fileName")
    content_type = body.get("contentType", "application/octet-stream")

    if not file_name:
        return {
            "status": "error",
            "message": "Missing required field 'fileName' in request body."
        }

    bucket_name, key_prefix = _get_bucket_and_key_prefix()
    object_key = f"{key_prefix}{file_name}"

    try:
        presigned_url = s3_client.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": bucket_name,
                "Key": object_key,
                "ContentType": content_type,
                "ServerSideEncryption": "aws:kms",
            },
            ExpiresIn=UPLOAD_URL_EXPIRATION,
            HttpMethod="PUT",
        )

        return {
            "status": "success",
            "uploadUrl": presigned_url,
            "bucket": bucket_name,
            "key": object_key,
            "expiresIn": UPLOAD_URL_EXPIRATION,
            "uploadType": "kb-sync",
        }

    except Exception as e:
        logger.exception("Error generating presigned URL")
        print(f"ERROR generating presigned URL: {e}")
        return {
            "status": "error",
            "message": "Failed to generate upload URL"
        }


@logger.inject_lambda_context
@tracer.capture_lambda_handler
@metrics.log_metrics
def lambda_handler(event: dict, context: LambdaContext):
    try:
        print("new packges setup")
    except Exception:
        pass
    return app.resolve(event, context)

# New tile data dictionary with PDF documentation naming
# This uses hyphenated names as specified in the Tiles Endpoint Documentation PDF
# 
# NOTE: This dictionary is now empty after the tile cleanup and standardization project.
# All tiles have been converted to query database views directly and no longer use static data.
# Static fallback is only used for tiles that don't have database implementations.
TILE_DATA = {
    # No static tiles remain - all tiles have been converted to database queries
}


# ============================================================================
# Helper Functions
# ============================================================================

def validate_date_format(date_string: str) -> tuple[bool, str]:
    """
    Validate that a date string is in ISO 8601 format (YYYY-MM-DD).
    
    Args:
        date_string: The date string to validate
    
    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if the date is valid, False otherwise
        - error_message: Empty string if valid, error description if invalid
    
    Examples:
        >>> validate_date_format("2025-01-15")
        (True, "")
        >>> validate_date_format("2025-1-15")
        (False, "Invalid date format. Expected ISO 8601 format (YYYY-MM-DD)")
        >>> validate_date_format("invalid")
        (False, "Invalid date format. Expected ISO 8601 format (YYYY-MM-DD)")
    """
    if not date_string:
        return True, ""  # Empty/None dates are valid (optional parameter)
    
    try:
        # Attempt to parse the date string
        parsed_date = datetime.strptime(date_string, "%Y-%m-%d")
        
        # Verify the format matches exactly (prevents dates like "2025-1-5" from passing)
        if date_string != parsed_date.strftime("%Y-%m-%d"):
            return False, "Invalid date format. Expected ISO 8601 format (YYYY-MM-DD)"
        
        return True, ""
    except ValueError:
        return False, "Invalid date format. Expected ISO 8601 format (YYYY-MM-DD)"


def validate_segment_parameter(segment: str) -> tuple[bool, str]:
    """
    Validate that a segment parameter is one of the allowed values.
    
    Args:
        segment: The segment string to validate
    
    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if the segment is valid, False otherwise
        - error_message: Empty string if valid, error description if invalid
    
    Examples:
        >>> validate_segment_parameter("340B")
        (True, "")
        >>> validate_segment_parameter("non-340B")
        (True, "")
        >>> validate_segment_parameter("invalid")
        (False, "Invalid segment value. Expected '340B' or 'non-340B'")
    """
    if not segment:
        return True, ""  # Empty/None segment is valid (optional parameter)
    
    allowed_segments = ["340B", "non-340B"]
    if segment not in allowed_segments:
        return False, f"Invalid segment value. Expected '340B' or 'non-340B', got '{segment}'"
    
    return True, ""


def validate_limit_parameter(limit: str) -> tuple[bool, str, int]:
    """
    Validate and convert a limit parameter to integer.
    
    Args:
        limit: The limit string to validate and convert
    
    Returns:
        Tuple of (is_valid, error_message, converted_value)
        - is_valid: True if the limit is valid, False otherwise
        - error_message: Empty string if valid, error description if invalid
        - converted_value: Integer value if valid, None if invalid
    
    Examples:
        >>> validate_limit_parameter("10")
        (True, "", 10)
        >>> validate_limit_parameter("invalid")
        (False, "Invalid limit parameter. Expected positive integer", None)
        >>> validate_limit_parameter("-5")
        (False, "Invalid limit parameter. Expected positive integer", None)
    """
    if not limit:
        return True, "", None  # Empty/None limit is valid (optional parameter)
    
    try:
        limit_int = int(limit)
        if limit_int <= 0:
            return False, "Invalid limit parameter. Expected positive integer", None
        return True, "", limit_int
    except (ValueError, TypeError):
        return False, "Invalid limit parameter. Expected positive integer", None


def validate_tile_name(tile_name: str) -> tuple[bool, str]:
    """
    Validate that a tile name follows kebab-case naming convention.
    
    Args:
        tile_name: The tile name to validate
    
    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if the tile name is valid, False otherwise
        - error_message: Empty string if valid, error description if invalid
    
    Examples:
        >>> validate_tile_name("anomalous-transactions")
        (True, "")
        >>> validate_tile_name("anomalousTransactions")
        (False, "Invalid tile name format. Expected kebab-case (lowercase with hyphens)")
        >>> validate_tile_name("ANOMALOUS-TRANSACTIONS")
        (False, "Invalid tile name format. Expected kebab-case (lowercase with hyphens)")
    """
    if not tile_name:
        return False, "Tile name cannot be empty"
    
    # Check if tile name follows kebab-case convention
    # Should be lowercase letters, numbers, and hyphens only
    # Should not start or end with hyphen
    # Should not have consecutive hyphens
    import re
    kebab_case_pattern = r'^[a-z0-9]+(-[a-z0-9]+)*$'
    
    if not re.match(kebab_case_pattern, tile_name):
        return False, "Invalid tile name format. Expected kebab-case (lowercase with hyphens)"
    
    return True, ""


def _classify_database_error(exception: Exception, tile_name: str, table_name: str = "database table", is_view: bool = False) -> dict:
    """
    Classify a database exception and return the appropriate error response.
    
    Args:
        exception: The exception that was raised
        tile_name: Name of the tile for error reporting
        table_name: Name of the table/view for error messages (default: "database table")
        is_view: Boolean indicating if the table_name refers to a view (default: False)
    
    Returns:
        Dictionary with error response containing error type and message
    """
    error_message = str(exception).lower()
    
    if ERROR_DOES_NOT_EXIST in error_message or ERROR_UNKNOWN_TABLE in error_message:
        error_type = "View does not exist" if is_view else "Table not found"
        return create_error_response(
            error_type,
            f"Database view {table_name} does not exist" if is_view else f"Database table {table_name} does not exist",
            tile_name
        )
    
    if "connection" in error_message or "connect" in error_message:
        return create_error_response(
            CONNECTION_FAILED,
            ERROR_CONNECTION,
            tile_name
        )
    
    return create_error_response(
        INTERNAL_SERVER_ERROR,
        f"An unexpected error occurred: {str(exception)}",
        tile_name
    )


def validate_account_id_parameters(query_params: dict, tile_name: str) -> tuple[bool, dict, str, str]:
    """
    Validate that exactly one of 340bId or pharmacyId is provided.
    
    This function enforces the mutual exclusivity requirement for account ID parameters.
    Exactly one of 340bId or pharmacyId must be provided, but not both and not neither.
    
    Args:
        query_params: Dictionary of query parameters to validate
        tile_name: Name of the tile for error reporting
    
    Returns:
        Tuple of (is_valid, error_response, id_type, id_value)
        - is_valid: True if validation passes, False otherwise
        - error_response: Error response dict if invalid, empty dict if valid
        - id_type: "340B" or "Pharmacy" if valid, None if invalid
        - id_value: The ID value if valid, None if invalid
    
    Examples:
        >>> validate_account_id_parameters({"340bId": "123"}, "test-tile")
        (True, {}, "340B", "123")
        >>> validate_account_id_parameters({"pharmacyId": "456"}, "test-tile")
        (True, {}, "Pharmacy", "456")
        >>> validate_account_id_parameters({}, "test-tile")
        (False, {"error": "Missing required parameter", ...}, None, None)
        >>> validate_account_id_parameters({"340bId": "123", "pharmacyId": "456"}, "test-tile")
        (False, {"error": "Invalid parameters", ...}, None, None)
    
    Validates: Requirements 10.1, 10.2
    """
    if not query_params:
        return False, {
            "error": MISSING_REQUIRED_PARAMETER,
            "message": EITHER_340BID_OR_PHARMACYID_REQUIRED,
            "tileName": tile_name
        }, None, None
    
    # Extract both parameters
    id_340b = query_params.get('340bId')
    pharmacy_id = query_params.get('pharmacyId')
    
    # Check if neither parameter is provided
    if not id_340b and not pharmacy_id:
        return False, {
            "error": MISSING_REQUIRED_PARAMETER,
            "message": EITHER_340BID_OR_PHARMACYID_REQUIRED,
            "tileName": tile_name
        }, None, None
    
    # Check if both parameters are provided
    if id_340b and pharmacy_id:
        return False, {
            "error": INVALID_PARAMS,
            "message": "Cannot specify both 340bId and pharmacyId. Provide exactly one.",
            "tileName": tile_name
        }, None, None
    
    # Validate 340bId if provided
    if id_340b:
        if not id_340b.strip():
            return False, {
                "error": INVALID_PARAMS,
                "message": "340bId parameter cannot be empty",
                "tileName": tile_name
            }, None, None
        return True, {}, "340B", id_340b.strip()
    
    # Validate pharmacyId (must be the one provided at this point)
    if not pharmacy_id.strip():
        return False, {
            "error": "Invalid parameters",
            "message": "pharmacyId parameter cannot be empty",
            "tileName": tile_name
        }, None, None
    return True, {}, "Pharmacy", pharmacy_id.strip()


def validate_query_parameters(query_params: dict, tile_name: str) -> tuple[bool, dict]:
    """
    Validate common query parameters for tile requests.
    
    Args:
        query_params: Dictionary of query parameters to validate
        tile_name: Name of the tile for error reporting
    
    Returns:
        Tuple of (is_valid, error_response_or_empty_dict)
        - is_valid: True if all parameters are valid, False otherwise
        - error_response_or_empty_dict: Error response dict if invalid, empty dict if valid
    
    Validates:
        - from: ISO 8601 date format (YYYY-MM-DD)
        - to: ISO 8601 date format (YYYY-MM-DD)
        - segment: "340B" or "non-340B"
        - limit: Positive integer
        - region: Non-empty string
    """
    if not query_params:
        return True, {}
    
    # Validate date parameters ('from' and 'to')
    for param_name in ('from', 'to'):
        is_valid, error_resp = validate_optional_param(
            query_params, param_name, validate_date_format, "Invalid date format", tile_name
        )
        if not is_valid:
            return False, error_resp
    
    # Validate 'segment' parameter
    is_valid, error_resp = validate_optional_param(
        query_params, 'segment', validate_segment_parameter, "Invalid segment value", tile_name
    )
    if not is_valid:
        return False, error_resp
    
    # Validate 'limit' parameter
    is_valid, error_resp = validate_optional_param(
        query_params, 'limit', validate_limit_parameter, "Invalid limit parameter", tile_name
    )
    if not is_valid:
        return False, error_resp
    
    # Validate 'region' parameter (if present, should be non-empty string)
    region = query_params.get('region')
    if region is not None and not region.strip():
        return False, create_error_response(
            "Invalid region parameter",
            "Region parameter cannot be empty",
            tile_name
        )

    time_period = query_params.get('time-period')
    valid_time_periods = ["quarterly", "monthly", "half-yearly", "yearly"]
    if time_period and time_period not in valid_time_periods:
        return False, create_error_response(
            INVALID_TIME_PERIOD,
            f"'time-period' parameter must be one of {valid_time_periods} but got {time_period}",
            tile_name
        )

    return True, {}


def generate_global_filters_from_query_params(query_params: dict, column_map: dict) -> str:
    """
    Generate global filters from query parameters based on a column mapping. The returned filter string is a continous condition starting with `AND` clause that can be applied to any database query for consistent filtering across all tiles. 
    This function abstracts the filter generation logic and allows for flexible mapping of query parameters to database columns.

    supported global filters include:
    - Brand : Filter by brand names (supports multiple comma-separated values)
    - State : Filter by state names (supports multiple comma-separated values)
    - Days Open : Filter by range of days open (expects format "min-max", e.g. "30-60" to filter for records with days open between 30 and 60)
    - Anomaly Status : Filter by anomaly types (supports multiple comma-separated values)
    - Customer type : Filter by customer types (supports multiple comma-separated values)

    Args:
        query_params: Dictionary of query parameters
        column_map: Dictionary mapping query parameter names to column names

    Returns:
        SQL filter string to be applied to database queries, based on provided query parameters and column mapping.
    """
    filter_parts = []

    for column in query_params:
        if column not in column_map or not query_params.get(column):
            continue

        db_column = column_map[column]
        raw_value = query_params[column]

        if column == 'daysOpen':
            clause = build_days_open_filter(raw_value, db_column)
        else:
            clause = build_in_clause_filter(raw_value, db_column)

        if clause:
            filter_parts.append(clause)

    return "".join(f"AND {part}" for part in filter_parts)

def get_date_for_time_period(period: str) -> str:
    """
    Get the date string for a given time period relative to the current date.
    
    Args:
        period: Time period string (e.g., "monthly", "quarterly", "yearly")
    
    Returns:
        Date string in ISO format (YYYY-MM-DD) representing the start date of the specified time period
    
    Examples:
        >>> get_date_for_time_period("monthly")
        "2024-01-01"  # Assuming today is 2024-01-15
        >>> get_date_for_time_period("quarterly")
        "2023-12-16"  # Assuming today is 2024-01-15
        >>> get_date_for_time_period("yearly")
        "2023-01-01"  # Assuming today is 2024-01-15
    """
    
    if MAX_TIME_PERIOD is None:
        logger.error("MAX_TIME_PERIOD is None; vwMaxTimePeriod query failed at startup.")
        return None

    if period == "monthly":
        target_date = MAX_TIME_PERIOD["max_date"]
    elif period == "quarterly":
        target_date = MAX_TIME_PERIOD["max_quarter_date"]
    elif period == "yearly":
        target_date = MAX_TIME_PERIOD["max_complete_year_date"]
    elif period == "half-yearly":
        target_date = MAX_TIME_PERIOD["max_half_year_date"]
    else:
        logger.warning(f"Unsupported time period: {period}. Defaulting to quarterly.")
        target_date = MAX_TIME_PERIOD["max_quarter_date"]

    return target_date

def process_summary_kpis(raw_query, query_params, session, tile_name, valid_filter_column_map, query_placeholder_values):
    """
    Helper function to process summary KPI queries for account detail KPIs.
    
    Args:
        query_template: The SQL query template to execute
        query_params: Dictionary of query parameters for filtering
        session: Database session object
        tile_name: Name of the tile for error reporting

    Returns:
        Dictionary containing:
            - current_value: The KPI value for the current period (float or None)
            - previous_value: The KPI value for the previous period (float or None)
        On error, returns error object with "error", "message", and "tileName" fields.
    """    
    try:
        filter_string = generate_global_filters_from_query_params(query_params, valid_filter_column_map)
        query = text(raw_query.format(query_params=filter_string))
        
        rows = session.execute(query, query_placeholder_values).fetchall()
        
        output = {}
        if rows:
            output["current_value"] = float(rows[0].value) if rows[0].value is not None else 0
            if 'timeperiod' in [col.lower() for col in rows[0]._mapping.keys()]:
                output["current_period"] = rows[0].TimePeriod
        

            if len(rows) > 1:
                output["previous_value"] = float(rows[1].value) if rows[1].value is not None else 0
                if 'timeperiod' in [col.lower() for col in rows[1]._mapping.keys()]:
                    output["previous_period"] = rows[1].TimePeriod

            return output
        else:
            logger.error(f"No data returned for KPI with filters: {query_params}")
            return {
                "no_data": True,
                "current_value": 0,
                "previous_value": 0
            }
    except Exception as e:
        logger.error(f"Error processing summary KPIs for {tile_name}: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e),
            "tileName": tile_name
        }



# ============================================================================
# Individual Tile Data Functions
# ============================================================================

def _get_days_open_mapping():
    """
    Map shorthand daysOpen bucket values to their full database equivalents.
    Allows UI/API to use shorthand like '0-7' instead of '0-7 Days'.
    """
    return {
        '0-7': '0-7 Days',
        '8-30': '8-30 Days',
        '31-60': '31-60 Days',
        '60+': '60+ Days',
    }


def _convert_days_open_values(days_open_str: str) -> list:
    """
    Convert shorthand daysOpen values (comma-separated) to full database bucket names.
    Example: '0-7,31-60' -> ['0-7 Days', '31-60 Days']
    """
    mapping = _get_days_open_mapping()
    values = [v.strip() for v in days_open_str.split(',') if v.strip()]
    converted = []
    
    for v in values:
        # Try exact match first
        if v in mapping:
            converted.append(mapping[v])
        else:
            # If not in mapping, use as-is (assume it's already a full DB value)
            converted.append(v)
    
    return converted


def _get_status_mapping():
    """
    Map shorthand status values to their full database equivalents.
    Allows UI/API to use simple names like 'Open' instead of 'Open (Unread)'.
    """
    return {
        'Open': 'Open (Unread)',
        'Closed': 'Closed',
        'Under HRSA Audit': 'Under HRSA Audit',
        'Under Investigation': 'Under Investigation',
        'Resolved': 'Resolved (after letter)',
        'False Positive': 'False Positive',
        'Letter Sent': 'Letter Sent',
        'Under Internal Audit': 'Under Internal Audit',
        'Pending': 'Letter Sent',  # Map "Pending" to LETTER_SENT
    }


def _convert_status_values(status_str: str) -> list:
    """
    Convert shorthand status values (comma-separated) to full database status values.
    Example: 'Open,Closed' -> ['Open (Unread)', 'Closed']
    """
    mapping = _get_status_mapping()
    values = [v.strip() for v in status_str.split(',') if v.strip()]
    converted = []
    
    for v in values:
        # Try exact match first
        if v in mapping:
            converted.append(mapping[v])
        else:
            # If not in mapping, use as-is (assume it's already a full DB value)
            converted.append(v)
    
    return converted


def _build_in_filter(param_value: str, column: str, key_prefix: str, filters: list, bind_params: dict, is_status: bool = False, is_days_open: bool = False):
    """
    Splits a comma-separated param value and appends either:
      col = :key              (single value)
      col IN (:key_0, ...)    (multiple values)
    to filters, populating bind_params accordingly.
    
    If is_status=True, converts shorthand status values to full DB status values.
    If is_days_open=True, converts shorthand daysOpen values to full DB bucket names.
    """
    if is_status:
        values = _convert_status_values(param_value)
    elif is_days_open:
        values = _convert_days_open_values(param_value)
    else:
        values = [v.strip() for v in param_value.split(',') if v.strip()]
    
    if not values:
        return
    if len(values) == 1:
        filters.append(f"{column} = :{key_prefix}")
        bind_params[key_prefix] = values[0]
    else:
        placeholders = ', '.join(f":{key_prefix}_{i}" for i in range(len(values)))
        filters.append(f"{column} IN ({placeholders})")
        for i, v in enumerate(values):
            bind_params[f"{key_prefix}_{i}"] = v


def get_summary_kpis_data(query_params: dict = None):
    """
    Fetch summary KPI metrics for the dashboard (v4 field names).
    Database tables Queried:
    - 340B_340BPurchases
    - 340B_Anomalies
    - 340B_CoveredEntities
    
    Args:
        query_params: dict of query parameters for filtering (e.g., time-period, brands, state)

    Returns:
        Dictionary with KPI metrics and period comparisons, or standardized error response on failure.
    """
    tile_name = "summary-kpis"
    session = None
    valid_filters = {
        "TOT_340B_UNITS": {
                "brands": "Brand",
                "states": "State"
            },
        "TOT_340B_WAC" : {
                "brands": "Brand",
                "states": "State"
            },
        "ACTIVE_ANOMALIES" : {
                "brands": "Anomaly_Brand",
                "states": "State"
            },
        "RISK_EXPOSURE" : {
                "brands": "Anomaly_Brand",
                "states": "State"
            },
    }
    filter_string = ""

    try:
        if query_params:
            is_valid, error_response = validate_query_parameters(query_params, tile_name)
            if not is_valid:
                return error_response
            
            time_period = query_params.get('time-period')
            valid_time_periods = ["quarterly", "monthly", "half-yearly"]
            if time_period and time_period not in valid_time_periods:
                return {
                    "error": INVALID_TIME_PERIOD,
                    "message": f"'time-period' parameter must be one of {valid_time_periods} but got {time_period}",
                    "tileName": tile_name
                }


        # Build WHERE filters from query_params.
        # This tile should always include only participating records.

        session = get_session()
        result = {}
        current_period=""
        previous_period=""
        count=0
        for kpi in OverviewSummaryKPI:
            filter_string = ""
            logger.info(f"Querying KPI {kpi.name} for filters filters: {query_params}")
            
            # implement filter generation based on query_params for supported filters
            filter_string = generate_global_filters_from_query_params(query_params, valid_filters.get(kpi.name, {}))

            query = text(kpi.value.format(query_params=filter_string))
            query_placeholder_values = {
            "time_period": time_period if query_params and query_params.get('time-period') else 'quarterly',
            "max_date": get_date_for_time_period(time_period if query_params and query_params.get('time-period') else 'quarterly')
            }

            output = session.execute(query, query_placeholder_values)
            rows = output.fetchall()
            
            if rows:
                if not current_period:
                    current_period=rows[0].TimePeriod

                if not previous_period and len(rows) > 1:
                    previous_period=rows[1].TimePeriod
                
                result[kpi.name] = {
                    "current_value": float(rows[0].value) if rows[0].value is not None else None,
                    "previous_value": float(rows[1].value) if len(rows) > 1 and rows[1].value is not None else None
                }
            
            else:
                logger.error(f"No data returned for KPI {kpi.name} with filters: {query_params}")
                count+=1
                result[kpi.name] = {
                    "current_value": None,
                    "previous_value": None
                }

        if count == len(OverviewSummaryKPI):
            return {
                "error": NO_DATA_FOUND,
                "message": NO_DATA_AVAILABLE_FOR_SPECIFIED_PARAMETERS,
                "tileName": tile_name
            }

        return {
            "currentPeriod": current_period,
            "prevPeriod": previous_period,
            "coveredEntities": result["TOTAL_CE_COUNT"]["current_value"] or 0,
            "coveredEntitiesCompareToPrevious":  calculate_percentage_change(result["TOTAL_CE_COUNT"]["current_value"], result["TOTAL_CE_COUNT"]["previous_value"]),
            "activeAnomalies": result["ACTIVE_ANOMALIES"]["current_value"] or 0,
            "activeAnomaliesCompareToPrevious": calculate_percentage_change(result["ACTIVE_ANOMALIES"]["current_value"], result["ACTIVE_ANOMALIES"]["previous_value"]),
            "unitVolume340b": {
                "count": result["TOT_340B_UNITS"]["current_value"] or 0,
                "dollars": result["TOT_340B_WAC"]["current_value"] or 0
            },
            "unitVolume340bCompareToPrevious": calculate_percentage_change(result["TOT_340B_UNITS"]["current_value"], result["TOT_340B_UNITS"]["previous_value"]),
            "riskExposure": result["RISK_EXPOSURE"]["current_value"] or 0,
            "riskExposureCompareToPrevious": calculate_percentage_change(result["RISK_EXPOSURE"]["current_value"], result["RISK_EXPOSURE"]["previous_value"])
        }

    except Exception as e:
        logger.error(f"Error fetching {tile_name} data: {e}")
        error_message = str(e).lower()
        if ERROR_DOES_NOT_EXIST in error_message or ERROR_UNKNOWN_TABLE in error_message:
            return {
                "error": VIEW_NOT_FOUND,
                "message": f"Database table does not exist: {str(e)}",
                "tileName": tile_name
            }
        elif "connection" in error_message or "connect" in error_message:
            return {
                "error": CONNECTION_FAILED,
                "message": ERROR_CONNECTION,
                "tileName": tile_name
            }
        else:
            return {
                "error": INTERNAL_SERVER_ERROR,
                "message": f"An unexpected error occurred: {str(e)}",
                "tileName": tile_name
            }
    finally:
        if session:
            session.close()


def get_anomalies_list_data(query_params: dict = None):
    """
    Fetch list of anomalies with joined HRSA data for All Anomalies page.
    
    Database View: vwThreeFourtyBAnomaliesTable
    
    This tile returns a list of anomalies (with Anomaly_LinkageScore >= 2) joined with HRSA
    entity information, limited to 100 results. The data includes anomaly details
    along with entity information from the HRSA database.
    
    Args:
        query_params: Optional dictionary of query parameters for filtering
            - from: Start date for filtering (optional, format: YYYY-MM-DD)
            - to: End date for filtering (optional, format: YYYY-MM-DD)
            - accountId: Filter by specific 340B account ID (optional)
            - segment: Segment filter - "340B" or "non-340B" (optional)
    
    Returns:
        List of dictionaries with actual UI column structure containing:
            - anomalyId: 8-character unique identifier for the anomaly (generated)
            - linkageScore: Linkage score percentage (0-100)
            - anomalyEntityName: Name of the entity with anomaly
            - brand: Brand name associated with the anomaly
            - anomalyDate: Date of the anomaly (format: MM/DD/YYYY)
            - daysOpen: Number of days the anomaly has been open (e.g., "1 Day", "7 Days")
            - region: Geographic region where the entity is located
            - units: Units field as shown in UI "Units" column
            - dollars: Dollars field as shown in UI "Dollars" column
            - action: Action field with valid status values as shown in UI "Action" column
            - state: State where the entity is located
            - city: City where the entity is located
        On error, returns error object with "error", "message", and "tileName" fields.
    
    Implementation:
        Queries vwThreeFourtyBAnomaliesTable view directly using simple SELECT statement.
        The view handles all complex SQL logic including JOINs, filtering, and formatting.
    """
    tile_name = "anomalies-list"
    session = None
    
    try:
        # Validate query parameters if provided
        if query_params:
            is_valid, error_response = validate_query_parameters(query_params, tile_name)
            if not is_valid:
                return error_response
        
        # Get database session
        session = get_session()
        
        # Query the view with simple SELECT statement
        # Note: The view already handles filtering (Anomaly_LinkageScore >= 2) and limit (100)
        result = session.execute(text("""
        SELECT
            anomalyId,
            accountId,
            linkageScore,
            anomalyEntityName,
            brand,
            anomalyDate,
            daysOpen,
            region,
            units,
            dollars,
            action,
            state,
            city
        FROM vwThreeFourtyBAnomaliesTable """)).fetchall()
        
        # Handle no data case
        if not result:
            return []
        
        # Map view columns to response format
        anomalies_list = []
        for row in result:
            anomalies_list.append({
                "anomalyId": row.anomalyId,
                "accountId": row.accountId,
                "linkageScore": row.linkageScore,
                "anomalyEntityName": row.anomalyEntityName,
                "brand": row.brand,
                "anomalyDate": row.anomalyDate,
                "daysOpen": row.daysOpen,
                "region": row.region,
                "units": row.units,
                "dollars": row.dollars,
                "action": row.action,
                "state": row.state,
                "city": row.city
            })
        
        return anomalies_list
        
    except Exception as e:
        # Check for specific error types
        error_message = str(e).lower()
        
        if ERROR_DOES_NOT_EXIST in error_message or "unknown" in error_message:
            logger.error(f"View not found for {tile_name}: {e}")
            return {
                "error": VIEW_NOT_FOUND,
                "message": "Database view vwThreeFourtyBAnomaliesTable does not exist",
                "tileName": tile_name
            }
        elif "connection" in error_message or "connect" in error_message:
            logger.error(f"Database connection error for {tile_name}: {e}")
            return {
                "error": CONNECTION_FAILED,
                "message": "Unable to connect to database",
                "tileName": tile_name
            }
        else:
            logger.error(f"Unexpected error fetching {tile_name} data: {e}")
            return {
                "error": INTERNAL_SERVER_ERROR,
                "message": f"An unexpected error occurred: {str(e)}",
                "tileName": tile_name
            }
    finally:
        # Always close the session
        if session:
            session.close()



def get_accounts_summary_kpis_data(query_params: dict = None):
    """
    Fetch account summary KPI metrics for the All Accounts page (accounts-summary-kpis tile).
    
    Database View: vwAccountsSummaryKpis
    
    This tile returns four key performance indicators for the All Accounts page:
        - threeFourtyBAccounts: Count of 340B accounts
        - contractPharmacyAccounts: Count of contract pharmacy accounts  
        - totalAnomalies: Total anomalies across all accounts
        - totalChargebacks: Total chargeback amount formatted as "$XXXk"
        Each metric includes comparison values with +/- prefixes
    
    Args:
        query_params: Optional dictionary of query parameters for filtering
            - brands: Filter by brand names (optional, supports multiple comma-separated values)
            - state: Filter by state names (optional, supports multiple comma-separated values)
    
    Returns:
        Dictionary with four KPI metrics:
        - threeFourtyBAccounts: Count of 340B accounts (integer)
        - threeFourtyBAccountsCompareToPrevious: Comparison value (string with +/- prefix)
        - contractPharmacyAccounts: Count of contract pharmacy accounts (integer)
        - contractPharmacyAccountsCompareToPrevious: Comparison value (string with +/- prefix)
        - totalAnomalies: Total anomalies count (integer)
        - totalAnomaliesCompareToPrevious: Comparison value (string with +/- prefix)
        - totalChargebacks: Total chargeback amount formatted as "$XXXk" (string)
        - totalChargebacksCompareToPrevious: Comparison value (string with +/- prefix)
        On error, returns error object with "error", "message", and "tileName" fields.
    
    """
    tile_name = "accounts-summary-kpis"
    session = None
    valid_filter_columns_map = {
        "ACCOUNT_COUNT": {
            "brands": "Brand",
            "states": "State",
        },
        "TOTAL_PHARMACIES": {
            "brands": "Brand",
            "states": "State",
        },
        "TOT_ANOMALIES_ACCOUNTS": {
            "brands": "Anomaly_Brand",
            "states": "State", # need to enable customer type, days open, status,
        },
        "TOT_RISK_ACCOUNTS": {
            "brands": "Anomaly_Brand",
            "states": "State",
        }
    }
    time_period = "quarterly"  # default time period
    
    try:
        # STEP 1: Extract and validate query parameters
        if query_params:
            # Validate all query parameters using helper function
            is_valid, error_response = validate_query_parameters(query_params, tile_name)
            if not is_valid:
                return error_response
            time_period = query_params.get('time-period', time_period)
        # Query the view with simple SELECT statement
        query_placeholder_values = {
            "time_period": time_period,
            "max_date": get_date_for_time_period(time_period)
            }
        session = get_session()
        result = {}
        current_period=""
        previous_period=""
        no_data_str="No data available for the specified parameters for the KPIs"
        count=0
        for kpi in AllAccountsSummaryKPI:

            row = process_summary_kpis(kpi.value, query_params, session, tile_name, valid_filter_columns_map.get(kpi.name, {}), query_placeholder_values)

            # Check if process_summary_kpis returned an error
            if "error" in row:
                return row
            elif "no_data" in row:
                logger.warning(f"No data returned for KPI {kpi.name} in {tile_name}")
                count += 1
                no_data_str = no_data_str + f" {kpi.name},"

            result[kpi.name] = {"current_value": row.get("current_value",0), "previous_value": row.get("previous_value",0)} 

            current_period = row.get("current_period", current_period)
            previous_period = row.get("previous_period", previous_period)
            
        if count == len(AllAccountsSummaryKPI):
            return {"error": NO_DATA_FOUND,"message": no_data_str,"tileName": tile_name}
        
        return {
            "currentPeriod": current_period,
            "prevPeriod": previous_period,
            "threeFourtyBAccounts": result["ACCOUNT_COUNT"]["current_value"] or 0,
            "threeFourtyBAccountsCompareToPrevious": calculate_percentage_change(result["ACCOUNT_COUNT"]["current_value"], result["ACCOUNT_COUNT"]["previous_value"]),
            "contractPharmacyAccounts": result["TOTAL_PHARMACIES"]["current_value"] or 0,
            "contractPharmacyAccountsCompareToPrevious": calculate_percentage_change(result["TOTAL_PHARMACIES"]["current_value"], result["TOTAL_PHARMACIES"]["previous_value"]),
            "totalAnomalies": result["TOT_ANOMALIES_ACCOUNTS"]["current_value"] or 0,
            "totalAnomaliesCompareToPrevious": calculate_percentage_change(result["TOT_ANOMALIES_ACCOUNTS"]["current_value"], result["TOT_ANOMALIES_ACCOUNTS"]["previous_value"]),
            "totalChargebacks": result["TOT_RISK_ACCOUNTS"]["current_value"] or 0,
            "totalChargebacksCompareToPrevious": calculate_percentage_change(result["TOT_RISK_ACCOUNTS"]["current_value"], result["TOT_RISK_ACCOUNTS"]["previous_value"]),
            "nodataResponse": no_data_str if count > 0 else None
        }
        
    except ValueError as e:
        # Handle validation errors
        logger.error(f"Validation error in {tile_name}: {e}")
        return {"error": INVALID_PARAMS,"message": str(e),"tileName": tile_name}
    except Exception as e:
        # Handle unexpected errors
        logger.error(f"Unexpected error fetching {tile_name} data: {e}")
        return _classify_database_error(e, tile_name, "vwAnomalousTransactions /  340B_CoveredEntities",is_view=True)
    finally:
        # Always close the session
        if session:
            session.close()


def get_top_340b_accounts_data(query_params: dict = None):
    """
    Fetch ranked list of top 340B accounts with key metrics for the top-340b-accounts tile.
    
    Database View: vwTop340BAccounts
    
    This tile returns a list of 340B accounts ordered by significance (anomalies count DESC, 
    then chargeback amount DESC). Each account includes key metrics for monitoring and analysis.
    
    Args:
        query_params: Optional dictionary of query parameters for filtering
            - from: Start date for filtering (optional, format: YYYY-MM-DD)
            - to: End date for filtering (optional, format: YYYY-MM-DD)
            - segment: Segment filter - "340B" or "non-340B" (optional)
            - limit: Maximum number of results (optional, positive integer)
            - region: Geographic region filter (optional, non-empty string)
    
    Returns:
        Array of account objects with:
        - id: Unique account identifier (string)
        - name: Account name (string)
        - anomalies: Count of anomalies (integer)
        - brands: Comma-separated brand names (string)
        - region: Geographic region (string)
        - chargeback: Formatted chargeback amount (string)
        - wac: Formatted WAC amount (string)
        On error, returns error object with "error", "message", and "tileName" fields.
    
    Implementation:
        Queries vwTop340BAccounts view directly using simple SELECT statement.
        The view handles all complex SQL logic including JOINs, aggregations, and ranking.
        Lambda formats monetary values and handles no data scenarios by returning empty array.
    """
    tile_name = "top-340b-accounts"
    session = None
    
    try:
        # STEP 1: Extract and validate query parameters
        if query_params:
            # Validate all query parameters using helper function
            is_valid, error_response = validate_query_parameters(query_params, tile_name)
            if not is_valid:
                return error_response
        
        # STEP 2: Call database function with error handling
        # Query the view with simple SELECT statement
        session = get_session()
        result = session.execute(text("""
        SELECT
            id,
            name,
            anomalies,
            brands,
            region,
            chargeback,
            wac
        FROM vwTop340BAccounts
    """)).fetchall()
        
        # STEP 3: Check if database returned an error
        # Handle no data scenarios by returning empty array
        if not result:
            return []
        
        # STEP 4: Validate response structure
        if not isinstance(result, list):
            return {
                "error": "Invalid database response",
                "message": "Database returned unexpected data format",
                "tileName": tile_name
            }
        
        # STEP 5: Format response with proper field mapping and data types
        accounts_list = []
        for row in result:
            # Format monetary values appropriately
            chargeback_formatted = format_monetary_value(row.chargeback)
            wac_formatted = format_monetary_value(row.wac)
            
            accounts_list.append({
                "id": str(row.id) if row.id is not None else "",
                "name": row.name or "Unknown",
                "anomalies": int(row.anomalies) if row.anomalies is not None else 0,
                "brands": str(row.brands) if row.brands is not None else "",
                "region": row.region or "Unknown",
                "chargeback": chargeback_formatted,
                "wac": wac_formatted
            })
        
        # STEP 6: Return validated data
        return accounts_list
        
    except ValueError as e:
        # Handle validation errors
        logger.error(f"Validation error in {tile_name}: {e}")
        return {
            "error": INVALID_PARAMS,
            "message": str(e),
            "tileName": tile_name
        }
    except Exception as e:
        # Handle unexpected errors
        logger.error(f"Unexpected error fetching {tile_name} data: {e}")
        
        # Check for specific error types
        error_message = str(e).lower()
        if ERROR_DOES_NOT_EXIST in error_message or ERROR_UNKNOWN_TABLE in error_message:
            return {
                "error": VIEW_NOT_FOUND,
                "message": "Database view vwTop340BAccounts does not exist",
                "tileName": tile_name
            }
        elif "connection" in error_message or "connect" in error_message:
            return {
                "error": CONNECTION_FAILED,
                "message": ERROR_CONNECTION,
                "tileName": tile_name
            }
        else:
            return {
                "error": INTERNAL_SERVER_ERROR,
                "message": f"An unexpected error occurred: {str(e)}",
                "tileName": tile_name
            }
    finally:
        # Always close the session
        if session:
            session.close()


def format_monetary_value(value):
    """
    Format monetary values with appropriate unit suffixes.
    
    Args:
        value: Numeric value to format
    
    Returns:
        Formatted string with appropriate unit (e.g., "$125K", "$1.2M")
    """
    if value is None or value == 0:
        return "$0"
    
    # Convert to float for calculations
    amount = float(value)
    
    if amount >= 1000000:
        # Format as millions
        return f"${amount / 1000000:.1f}M"
    elif amount >= 1000:
        # Format as thousands
        return f"${amount / 1000:.0f}K"
    else:
        # Format as dollars
        return f"${amount:.0f}"


def get_contract_pharmacy_accounts_data(query_params: dict = None):
    """
    Fetch ranked list of contract pharmacy accounts with key metrics for the contract-pharmacy-accounts tile.
    
    Database View: vwContractPharmacyAccounts
    
    This tile returns a list of contract pharmacy accounts ordered by significance (anomalies count DESC, 
    then chargeback amount DESC). Each account includes key metrics for monitoring and analysis.
    
    Args:
        query_params: Optional dictionary of query parameters for filtering
            - from: Start date for filtering (optional, format: YYYY-MM-DD)
            - to: End date for filtering (optional, format: YYYY-MM-DD)
            - segment: Segment filter - "340B" or "non-340B" (optional)
            - limit: Maximum number of results (optional, positive integer)
            - region: Geographic region filter (optional, non-empty string)
    
    Returns:
        Array of account objects with:
        - id: Unique account identifier (string)
        - name: Account name (string)
        - anomalies: Count of anomalies (integer)
        - brands: Comma-separated brand names (string)
        - region: Geographic region (string)
        - chargeback: Formatted chargeback amount (string)
        - wac: Formatted WAC amount (string)
        On error, returns error object with "error", "message", and "tileName" fields.
    
    Implementation:
        Queries vwContractPharmacyAccounts view directly using simple SELECT statement.
        The view handles all complex SQL logic including JOINs, aggregations, and ranking.
        Lambda formats monetary values and handles no data scenarios by returning empty array.
    """
    tile_name = "contract-pharmacy-accounts"
    session = None
    
    try:
        # STEP 1: Extract and validate query parameters
        if query_params:
            # Validate all query parameters using helper function
            is_valid, error_response = validate_query_parameters(query_params, tile_name)
            if not is_valid:
                return error_response
        
        # STEP 2: Call database function with error handling
        # Query the view with simple SELECT statement
        session = get_session()
        result = session.execute(text("""
        SELECT
            id,
            name,
            anomalies,
            brands,
            region,
            chargeback,
            wac
        FROM vwContractPharmacyAccounts
    """)).fetchall()
        
        # STEP 3: Check if database returned an error
        # Handle no data scenarios by returning empty array
        if not result:
            return []
        
        # STEP 4: Validate response structure
        if not isinstance(result, list):
            return {
                "error": "Invalid database response",
                "message": "Database returned unexpected data format",
                "tileName": tile_name
            }
        
        # STEP 5: Format response with proper field mapping and data types
        accounts_list = []
        for row in result:
            # Format monetary values appropriately
            chargeback_formatted = format_monetary_value(row.chargeback)
            wac_formatted = format_monetary_value(row.wac)
            
            accounts_list.append({
                "id": str(row.id) if row.id is not None else "",
                "name": row.name or "Unknown",
                "anomalies": int(row.anomalies) if row.anomalies is not None else 0,
                "brands": str(row.brands) if row.brands is not None else "",
                "region": row.region or "Unknown",
                "chargeback": chargeback_formatted,
                "wac": wac_formatted
            })
        
        # STEP 6: Return validated data
        return accounts_list
        
    except ValueError as e:
        # Handle validation errors
        logger.error(f"Validation error in {tile_name}: {e}")
        return {
            "error": INVALID_PARAMS,
            "message": str(e),
            "tileName": tile_name
        }
    except Exception as e:
        # Handle unexpected errors
        logger.error(f"Unexpected error fetching {tile_name} data: {e}")
        
        # Check for specific error types
        error_message = str(e).lower()
        if ERROR_DOES_NOT_EXIST in error_message or ERROR_UNKNOWN_TABLE in error_message:
            return {
                "error": VIEW_NOT_FOUND,
                "message": "Database view vwContractPharmacyAccounts does not exist",
                "tileName": tile_name
            }
        elif "connection" in error_message or "connect" in error_message:
            return {
                "error": CONNECTION_FAILED,
                "message": ERROR_CONNECTION,
                "tileName": tile_name
            }
        else:
            return {
                "error": INTERNAL_SERVER_ERROR,
                "message": f"An unexpected error occurred: {str(e)}",
                "tileName": tile_name
            }
    finally:
        # Always close the session
        if session:
            session.close()


def get_340b_covered_entity_volume_data(query_params: dict = None):
    """
    Fetch 340B covered entity volume data for stacked area chart.
    
    Database View: vwThreeFourtyBCoveredEntityVolume
    
    This tile returns time series data showing 340B covered entity volume and percentage
    over time, formatted for a stacked area chart visualization.
    
    Args:
        query_params: Optional dictionary of query parameters for filtering
            - from: Start date for filtering (optional, format: YYYY-MM-DD)
            - to: End date for filtering (optional, format: YYYY-MM-DD)
    
    Returns:
        Dictionary containing:
            - categories: List of month names (e.g., ["Jan", "Feb", ...])
            - series: List of two data series:
                - "340B Covered Entity QTY": Volume quantities by month
                - "340B % Volume": Percentage volumes by month
        On error, returns error object with "error" and "message" fields.
    
    Implementation:
        Queries vwThreeFourtyBCoveredEntityVolume view directly to fetch
        actual 340B covered entity volumes aggregated by month.
    """
    tile_name = "340b-covered-entity-volume"
    session = None
    filter_string = ""
    time_period = "quarterly"
    valid_filter_column_map = {
        "brands": "Brand",
        "states": "State"
    }
    
    try:
            # Validate time-period parameter if provided
        if query_params:
            time_period = query_params.get('time-period',"quarterly") # default to quarterly if not provided
            valid_time_periods = ["quarterly", "monthly", "half-yearly","yearly"]
            if time_period and time_period not in valid_time_periods:
                return {
                    "error": INVALID_TIME_PERIOD,
                    "message": f"'time-period' parameter must be one of {valid_time_periods} but got {time_period}",
                    "tileName": tile_name
                }
            
            filter_string = generate_global_filters_from_query_params(query_params, valid_filter_column_map)
        
        # Query the view directly
        session = get_session()
        query = text(OverviewPageCharts.PER_VOLUME_340B.value.format(query_params=filter_string))
        query_placeholder_values = {
            "time_period": time_period,
            "max_date": get_date_for_time_period(time_period if query_params and query_params.get('time-period') else 'quarterly')
        }
        result = session.execute(query,query_placeholder_values)
        rows = result.fetchall()
        
        if not rows:
            # No data found, return empty structure
            return {
                "categories": [],
                "series": [
                    {
                        "name": "340B Covered Entity QTY",
                        "data": [],
                        "type": "area",
                        "yAxis": 0
                    },
                    {
                        "name": "340B % Volume",
                        "data": [],
                        "type": "area",
                        "yAxis": 1
                    }
                ]
            }
        
        # Extract data from query results
        categories = []
        covered_entity_qty_data = []
        volume_percentage_data = []
        
        for row in rows:
            categories.append(row.TimePeriod)
            covered_entity_qty_data.append(int(row.quantity) if row.quantity else 0)
            volume_percentage_data.append(int(row.volume_percentage) if row.volume_percentage else 0)
        
        # Build response structure matching the expected format
        tile_data = {
            "categories": categories,
            "series": [
                {
                    "name": "340B Covered Entity QTY",
                    "data": covered_entity_qty_data,
                    "type": "area",
                    "yAxis": 0
                },
                {
                    "name": "340B % Volume",
                    "data": volume_percentage_data,
                    "type": "area",
                    "yAxis": 1
                }
            ]
        }
        
        # Validate dual-series structure and handle error scenarios
        is_valid, error_response = handle_dual_series_error_scenarios(tile_data, tile_name)
        if not is_valid:
            return error_response
        
        return tile_data
        
    except Exception as e:
        logger.error(f"Error fetching 340B covered entity volume data: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e),
            "tileName": tile_name
        }
    finally:
        if session:
            session.close()


def get_dispense_vs_purchase_volume_data(query_params: dict = None):
    """
    Fetch dispense vs purchase volume data for line chart.
    
    Database View: vwDispenseVsPurchaseVolume
    
    This tile returns time series data comparing dispense quantity vs. purchase quantity
    over time, formatted for a line chart visualization.
    
    Args:
        query_params: Optional dictionary of query parameters for filtering
            - from: Start date for filtering (optional, format: YYYY-MM-DD)
            - to: End date for filtering (optional, format: YYYY-MM-DD)
    
    Returns:
        Dictionary containing:
            - categories: List of time periods (e.g., ["1", "2", ..., "12"])
            - series: List of two data series:
                - "Dispense Quantity": Dispense volumes by time period
                - "Purchase Quantity": Purchase volumes by time period
        On error, returns error object with "error" and "message" fields.
    
    Implementation:
        Queries vwDispenseVsPurchaseVolume view directly to fetch actual
        dispense and purchase volumes aggregated by month.
        Date range filtering is applied if from/to parameters are provided.
    """
    tile_name = "dispense-vs-purchase-volume"
    session = None
    time_period = "quarterly"
    filter_string = ""
    valid_filter_column_map = {
        "brands": "Brand",
        "states": "State"
    }
    
    try:
        
        # Validate time-period parameter if provided
        if query_params:
            time_period = query_params.get('time-period',"quarterly") # default to quarterly if not provided
            valid_time_periods = ["quarterly", "monthly", "half-yearly","yearly"]
            if time_period and time_period not in valid_time_periods:
                return {
                    "error": INVALID_TIME_PERIOD,
                    "message": f"'time-period' parameter must be one of {valid_time_periods} but got {time_period}",
                    "tileName": tile_name
                }
            
            filter_string = generate_global_filters_from_query_params(query_params,valid_filter_column_map)
        
        # Query the view directly
        raw_query = OverviewPageCharts.PUR_VS_DISP.value
        session = get_session()
        query = text(raw_query.format(query_params=filter_string if filter_string else ""))
        query_placeholder_values = {
            "time_period": time_period,
            "max_date": get_date_for_time_period(time_period if query_params and query_params.get('time-period') else 'quarterly')
        }
        result = session.execute(query,query_placeholder_values)
        rows = result.fetchall()
        
        if not rows:
            # No data found, return empty structure
            return {
                "categories": [],
                "series": [
                    {
                        "name": DISPENSE_QUANTITY,
                        "data": [],
                        "type": "line",
                        "yAxis": 0
                    },
                    {
                        "name": PURCHASE_QUANTITY,
                        "data": [],
                        "type": "line",
                        "yAxis": 1
                    }
                ]
            }
        
        # Extract data from query results
        categories = []
        dispense_data = []
        purchase_data = []
        
        for row in rows:
            categories.append(str(row.TimePeriod))
            dispense_data.append(int(row.dispenseQuantity) if row.dispenseQuantity else 0)
            purchase_data.append(int(row.purchaseQuantity) if row.purchaseQuantity else 0)
        
        # Build response structure matching the expected format
        tile_data = {
            "categories": categories,
            "series": [
                {
                    "name": DISPENSE_QUANTITY,
                    "data": dispense_data,
                    "type": "line",
                    "yAxis": 0
                },
                {
                    "name": PURCHASE_QUANTITY,
                    "data": purchase_data,
                    "type": "line",
                    "yAxis": 1
                }
            ]
        }
        
        # Validate dual-series structure and handle error scenarios
        is_valid, error_response = handle_dual_series_error_scenarios(tile_data, tile_name)
        if not is_valid:
            return error_response
        
        return tile_data
        
    except Exception as e:
        logger.error(f"Error fetching dispense vs purchase volume data: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e),
            "tileName": tile_name
        }
    finally:
        if session:
            session.close()

def get_340b_sales_discount_data(query_params: dict = None):
    """
    Fetch 340B sales and discount (WAC and Chargeback) data for column chart.
    The tile returns aggregated WAC and Chargeback amounts by time period (quarterly, monthly, half-yearly, or yearly) for 340B sales, formatted for a mixed column chart visualization, with demand trend lines.
    table: 340B_340BPurchases

    Args:
        query_params: Optional dictionary of query parameters for filtering
            - time-period: Time period for aggregation (optional, default: "quarterly", valid
    
    """
    tile_name="340b-sales-discount"
    session = None
    sales_valid_fliter_column_map = {
        "states": "STATE",
        "brands": "BRAND",
    }

    demand_valid_fliter_column_map = {
        "brands": "BRAND",
    }
    sales_filter_string = ""
    demand_filter_string = ""

    try:

        #validate query params
        if query_params:
            time_period = query_params.get('time-period')
            valid_time_periods = ["quarterly", "monthly", "half-yearly","yearly"]
            if time_period and time_period not in valid_time_periods:
                return {
                    "error": INVALID_TIME_PERIOD,
                    "message": f"'time-period' parameter must be one of {valid_time_periods} but got {time_period}",
                    "tileName": tile_name
                }
            
            sales_filter_string = generate_global_filters_from_query_params(query_params, sales_valid_fliter_column_map)
            demand_filter_string = generate_global_filters_from_query_params(query_params, demand_valid_fliter_column_map)
            
        session = get_sf_session()
        sales_raw_query = PowerBIReports.SALES_VS_DISCOUNTS.value
        demand_raw_query = PowerBIReports.DEMAND_PERC.value
        sales_query = text(sales_raw_query.format(query_params=sales_filter_string if sales_filter_string else ""))
        demand_query = text(demand_raw_query.format(query_params=demand_filter_string if demand_filter_string else ""))
        logger.info(f"Executing query for {tile_name} with time_period: {time_period if query_params and query_params.get('time-period') else 'quarterly'}")

        query_placeholder_values = {
            "time_period": time_period if query_params and query_params.get('time-period') else 'quarterly',
            "max_date": get_date_for_time_period(time_period if query_params and query_params.get('time-period') else 'quarterly')
        }
        sales_result = session.execute(sales_query, query_placeholder_values)
        sales_rows = sales_result.fetchall()

        categories = []
        wac_data = []
        chargeback_data = []
        for row in sales_rows:
            categories.append(row.timeperiod)
            wac_data.append(round(float(row.wac_sales)/1e6, 1) if row.wac_sales else 0) #representation in millions with 1 decimal point
            chargeback_data.append(round(float(row.chargeback)/1e6, 1) if row.chargeback else 0) #representation in millions with 1 decimal point

        demand_result = session.execute(demand_query, query_placeholder_values)
        demand_rows = demand_result.fetchall()

        demand_data=[]
        for row in demand_rows:
            demand_data.append(round(float(row.perc_demand), 1) if row.perc_demand else 0) #representation in percent with 1 decimal point

        tile_data = {
            "categories": categories,
            "series": [
                {
                    "name": "WAC",
                    "data": wac_data,
                    "type": "column",
                    "yAxis": 0
                },
                {
                    "name": "Chargeback",
                    "data": chargeback_data,
                    "type": "column",
                    "yAxis": 0
                },
                {
                    "name": "Demand %",
                    "data": demand_data,
                    "type": "line",
                    "yAxis": 1
                }
            ]
        }

        return tile_data
    except Exception as e:
        logger.error(f"Error fetching 340B sales discount data: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e),
            "tileName": tile_name
        }
    finally:
        if session:
            session.close()
    

def get_cecp_split_data(query_params: dict = None):
    """
    Fetch covered entity vs contract pharmacy split data for split column chart.
    
    This tile returns data showing the split of covered entity vs contract pharmacy volumes, along with the percentage discount across the time period,
    formatted for a mixed chart (bar and line) visualization.
    Table: 340B_ProcessedData
    
    Args:
        query_params: Optional dictionary of query parameters for filtering
            - time-period: Time period for filtering (optional, e.g., "quarterly", "monthly","half-yearly","yearly")
    """
    tile_name = "cecp-split"
    session = None
    valid_filter_column_map = {
        "states": "STATE",
        "brands": "BRAND",
    }
    filter_string = ""
    time_period = "quarterly" # default time period
    
    # Since the underlying data is not yet finalized, we will return a placeholder response
    # that matches the expected format for the UI team to work with.
    
    try:
        # Validate time-period parameter if provided
        if query_params:
            time_period = query_params.get('time-period',"quarterly") # default to quarterly if not provided
            valid_time_periods = ["quarterly", "monthly", "half-yearly","yearly"]
            if time_period and time_period not in valid_time_periods:
                return {
                    "error": INVALID_TIME_PERIOD,
                    "message": f"'time-period' parameter must be one of {valid_time_periods} but got {time_period}",
                    "tileName": tile_name
                }
            
            filter_string = generate_global_filters_from_query_params(query_params, valid_filter_column_map)
        
        # Query the view directly
        session = get_sf_session()
        # ctx = get_sf_conn()
        # con = ctx.cursor()
        raw_query = PowerBIReports.CECP_SPLIT.value
        query = text(raw_query.format(query_params=filter_string if filter_string else ""))
        # query = raw_query.format(query_params=filter_string if filter_string else "").replace(':time_period', time_period if time_period else 'quarterly').replace(':max_date', get_date_for_time_period(time_period if query_params and query_params.get('time-period') else 'quarterly')) # temp execution
        logger.info(f"Executing query for {tile_name} with time_period: {time_period if query_params and query_params.get('time-period') else 'quarterly'}")

        query_placeholder_values = {
            "time_period": time_period if query_params and query_params.get('time-period') else 'quarterly',
            "max_date": get_date_for_time_period(time_period if query_params and query_params.get('time-period') else 'quarterly')
        }
        result = session.execute(query, query_placeholder_values)
        # result = con.execute(query)
        rows = result.fetchall()

        categories = []
        ce_data = []
        cp_data = []
        perc_discount = []
        for row in rows: # need to manage the order of rows since we are doing a union all. Assuming the order is maintained as CE, CP, perc_discount for each time period and all three values are present for all time period.
            categories.append(row.timeperiod)
            # categories.append(row[0])
            ce_data.append(round(float(row.ce_wac)/1e6,1) if row.ce_wac else 0) #representation in millions with 1 decimal point
            # ce_data.append(round(float(row[2])/1e6,1) if row[2] else 0) # representation in millions with 1 decimal point
            cp_data.append(round(float(row.cp_wac)/1e6,1) if row.cp_wac else 0) # representation in millions with 1 decimal point
            # cp_data.append(round(float(row[3])/1e6,1) if row[3] else 0)
            perc_discount.append(float(row.perc_discount) if row.perc_discount else 0)
            # perc_discount.append(float(row[4]) if row[4] else 0)

        
        # split bar chart to accomodate dual axis with line chart for percentage discount
        tile_data = {
            "categories": categories,  # Use actual categories from query
            "series": [
                {
                    "name": "CE",
                    "data": ce_data,  # Use actual CE data from query
                    "type": "column",
                    "stack": "split",
                    "yAxis": 0
                },
                {
                    "name": "CP",
                    "data": cp_data,  # Use actual CP data from query
                    "type": "column",
                    "stack": "split",
                    "yAxis": 0
                },
                {
                    "name": "Discount %",
                    "data": perc_discount,  # Use actual discount data from query
                    "type": "line",
                    "yAxis": 1
                }
            ]
        }
        
        return tile_data
        
    except Exception as e:
        logger.error(f"Error fetching CE vs CP split data: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e),
            "tileName": tile_name
        }
    
    finally:
        if session:
            session.close()
        # con.close()
        # ctx.close()

def get_340b_wac_cecp(query_params: dict = None):

    """
    Fetches 340B WAC CECP data for mixed line and bar chart visualization.

    This tile returns data showing the WAC trends over the specified time period, along with the contribution of covered entities (CE) vs contract pharmacies (CP) to the overall WAC (in %),
    formatted for a mixed chart (bar and line) visualization.
    Table: 340B_ProcessedData
    
    Args:
        query_params: Optional dictionary of query parameters for filtering
            - time-period: Time period for filtering (optional, e.g., "quarterly", "monthly","half-yearly","yearly")
    """

    tile_name = "340b-wac-cecp"
    session = None
    valid_filter_column_map = {
        "states": "STATE",
        "brands": "BRAND",
    }
    filter_string = ""

    try:
        # Validate time-period parameter if provided
        if query_params:
            time_period = query_params.get('time-period')
            valid_time_periods = ["quarterly", "monthly", "half-yearly","yearly"]
            if time_period and time_period not in valid_time_periods:
                return {
                    "error": INVALID_TIME_PERIOD,
                    "message": f"'time-period' parameter must be one of {valid_time_periods} but got {time_period}",
                    "tileName": tile_name
                }
            
            filter_string = generate_global_filters_from_query_params(query_params, valid_filter_column_map)
        
        # Query the view directly
        session = get_sf_session()
        raw_query = PowerBIReports.WAC_340B_CECP.value
        
        query = text(raw_query.format(query_params=filter_string if filter_string else ""))
        logger.info(f"Executing query for {tile_name} with time_period: {time_period if query_params and query_params.get('time-period') else 'quarterly'}")
        query_placeholder_values = {
            "time_period": time_period if query_params and query_params.get('time-period') else 'quarterly',
            "max_date": get_date_for_time_period(time_period if query_params and query_params.get('time-period') else 'quarterly')
        }
        result = session.execute(query, query_placeholder_values)
        rows = result.fetchall()

        categories = []
        perc_ce_wac = []
        perc_cp_wac = []
        wac = []
        for row in rows:
            categories.append(row.timeperiod)
            perc_ce_wac.append(float(row.perc_ce_wac) if row.perc_ce_wac else 0)
            perc_cp_wac.append(float(row.perc_cp_wac) if row.perc_cp_wac else 0)
            wac.append(round(float(row.wac)/1e6, 1) if row.wac else 0) #representation in millions with 1 decimal point

        
        # bar chart to accomodate dual axis with line chart for CE & CP % volume against WAC
        # Implementation for tooltip display of complete WAC values is pending
        tile_data = {
            "categories": categories,  # Use actual categories from query
            "series": [
                {
                    "name": "CE",
                    "data": perc_ce_wac,  # Use actual CE data from query
                    "type": "line",
                    "yAxis": 1
                },
                {
                    "name": "CP",
                    "data": perc_cp_wac,  # Use actual CP data from query
                    "type": "line",
                    "yAxis": 1
                },
                {
                    "name": "WAC",
                    "data": wac,  # Use actual wac data from query
                    "type": "column",
                    "yAxis": 0
                }
            ]
        }
        
        return tile_data
        
    except Exception as e:
        logger.error(f"Error fetching 340B WAC CECP data: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e),
            "tileName": tile_name
        }
    
    finally:
        if session:
            session.close()

def get_340b_chbk_cecp(query_params: dict = None):

    """
    Fetches 340B Chargeback CECP data for mixed line and bar chart visualization.

    This tile returns data showing the Chargeback trends over the specified time period, along with the contribution of covered entities (CE) vs contract pharmacies (CP) to the overall Chargeback (in %),
    formatted for a mixed chart (bar and line) visualization.
    Table: 340B_ProcessedData
    
    Args:
        query_params: Optional dictionary of query parameters for filtering
            - time-period: Time period for filtering (optional, e.g., "quarterly", "monthly","half-yearly","yearly")
    """

    tile_name = "340b-chbk-cecp"
    session = None
    valid_filter_column_map = {
        "states": "STATE",
        "brands": "BRAND",
    }
    filter_string = ""

    try:
        # Validate time-period parameter if provided
        if query_params:
            time_period = query_params.get('time-period')
            valid_time_periods = ["quarterly", "monthly", "half-yearly","yearly"]
            if time_period and time_period not in valid_time_periods:
                return {
                    "error": INVALID_TIME_PERIOD,
                    "message": f"'time-period' parameter must be one of {valid_time_periods} but got {time_period}",
                    "tileName": tile_name
                }
            
            filter_string = generate_global_filters_from_query_params(query_params, valid_filter_column_map)
        
        # Query the view directly
        session = get_sf_session()
        raw_query = PowerBIReports.CHBK_340B_CECP.value
        
        query = text(raw_query.format(query_params=filter_string if filter_string else ""))
        logger.info(f"Executing query for {tile_name} with time_period: {time_period if query_params and query_params.get('time-period') else 'quarterly'}")

        query_placeholder_values = {
            "time_period": time_period if query_params and query_params.get('time-period') else 'quarterly',
            "max_date": get_date_for_time_period(time_period if query_params and query_params.get('time-period') else 'quarterly')
        }

        result = session.execute(query, query_placeholder_values)
        rows = result.fetchall()

        categories = []
        perc_ce_chbk = []
        perc_cp_chbk = []
        chbk = []
        for row in rows:
            categories.append(row.timeperiod)
            perc_ce_chbk.append(float(row.perc_ce_chbk) if row.perc_ce_chbk else 0)
            perc_cp_chbk.append(float(row.perc_cp_chbk) if row.perc_cp_chbk else 0)
            chbk.append(round(float(row.chbk)/1e6, 1) if row.chbk else 0)  # representation in millions with 1 decimal point

        
        # bar chart to accomodate dual axis with line chart for CE & CP % volume against Chargeback
        tile_data = {
            "categories": categories,  # Use actual categories from query
            "series": [
                {
                    "name": "CE",
                    "data": perc_ce_chbk,  # Use actual CE data from query
                    "type": "line",
                    "yAxis": 1
                },
                {
                    "name": "CP",
                    "data": perc_cp_chbk,  # Use actual CP data from query
                    "type": "line",
                    "yAxis": 1
                },
                {
                    "name": "Chargeback",
                    "data": chbk,  # Use actual Chargeback data from query
                    "type": "column",
                    "yAxis": 0
                }
            ]
        }
        
        return tile_data
        
    except Exception as e:
        logger.error(f"Error fetching 340B Chargeback CECP data: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e),
            "tileName": tile_name
        }
    
    finally:
        if session:
            session.close()

def get_top_340b_accounts_by_avg_hcp_purchase_data(query_params: dict = None):
    """
    Fetch top 340B accounts by average HCP purchase data for table visualization.
    
    This tile returns tabular data showing the top 10 340B accounts ranked by average HCP purchase amount, formatted for table visualization.
    Table: 340B_ProcessedData
    
    Args:
        query_params: Optional dictionary of query parameters for filtering
            - from: Start date for filtering (optional, format: YYYY-MM-DD)
    """

    tile_name = "top-340b-accounts-by-avg-hcp-purchase"
    session = None
    valid_filter_column_map = {
        "states": "PARENT_ENTITY_STATE",
        "brands": "BRAND",
    }
    filter_string = ""

    if query_params:
        time_period = query_params.get('time-period')
        valid_time_periods = ["monthly", "quarterly", "half-yearly", "yearly"]
        if time_period and time_period not in valid_time_periods:
            return {
                "error": INVALID_TIME_PERIOD,
                "message": f"'time-period' parameter must be one of {valid_time_periods} but got {time_period}",
                "tileName": tile_name
            }
        
        filter_string = generate_global_filters_from_query_params(query_params, valid_filter_column_map)
    
    try:
        session = get_sf_session()
        raw_query = PowerBIReports.TOP_ACCOUTS_BY_HCP.value
        query = text(raw_query.format(query_params=filter_string if filter_string else ""))
        query_placeholder_values = {
            "max_date": get_date_for_time_period('quarterly')
        }
        result = session.execute(query, query_placeholder_values)
        rows = result.fetchall()

        min_cohort = [] # > $450 Avg HCP sales
        mid_cohort = [] # $450 - $4k Avg HCP sales
        max_cohort = [] # > $4k Avg HCP sales
        for row in rows:

            avg_hcp_purchase = float(row.avg_hcp_purchase) if row.avg_hcp_purchase else 0

            if avg_hcp_purchase >4000:

                max_cohort.append({
                    "name": row.account_name,
                    "340b_id": row.parent_340b_id,
                    "x": row.hcp_count if row.hcp_count else 0,
                    "y": round(float(row.tot_wac_sales)/1e6, 1) if row.tot_wac_sales else 0, # representation in Millions with 1 decimal point
                    "z": round(float(row.avg_hcp_purchase)/1e3, 1) if row.avg_hcp_purchase else 0 # representation in Thousands with 1 decimal point
                }) 

            elif avg_hcp_purchase >450 and avg_hcp_purchase <=4000:

                mid_cohort.append({
                    "name": row.account_name,
                    "340b_id": row.parent_340b_id,
                    "x": row.hcp_count if row.hcp_count else 0,
                    "y": round(float(row.tot_wac_sales)/1e6, 1) if row.tot_wac_sales else 0, # representation in Millions with 1 decimal point
                    "z": round(float(row.avg_hcp_purchase)/1e3, 1) if row.avg_hcp_purchase else 0 # representation in Thousands with 1 decimal point
                })

            else:

                min_cohort.append({
                    "name": row.account_name,
                    "340b_id": row.parent_340b_id,
                    "x": row.hcp_count if row.hcp_count else 0,
                    "y": round(float(row.tot_wac_sales)/1e6, 1) if row.tot_wac_sales else 0, # representation in Millions with 1 decimal point
                    "z": round(float(row.avg_hcp_purchase)/1e3, 1) if row.avg_hcp_purchase else 0 # representation in Thousands with 1 decimal point
                })
        
        tile_data =[
        {
            "type":"min",
            "name": "Avg HCP Purchase < $450",
            "data": min_cohort
        },
        {
            "type":"mid",
            "name": "Avg HCP Purchase $450 - $4k",
            "data": mid_cohort
        },
        {
            "type":"max",
            "name": "Avg HCP Purchase > $4k",
            "data": max_cohort
        }
        ]

        return tile_data
    except Exception as e:
        logger.error(f"Error fetching top 340B accounts by average HCP purchase data: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e),
            "tileName": tile_name
        }
    finally:
        if session:
            session.close()

def get_chbk_per_day_data(query_params: dict = None):
    """
    Fetch chargeback per day data for line chart visualization. - Currently day level data is not available and thus returns monthly rollup data with date as first day of month. Once day level data is available, the query can be updated to return actual chargeback per day data.

    This tile returns time series data showing chargeback amount per day (currently monthly rollup) over time, formatted for a line chart visualization.
    Table: 340B_340BPurchases

    query_params: Optional dictionary of query parameters for filtering
        - time-period: Time period for filtering (optional, e.g., "quarterly", "monthly","half-yearly") - currently not implemented in query since day level data is not available
    """

    tile_name="chbk-per-day"
    session = None
    valid_filter_column_map = {
        "states": "STATE",
        "brands": "BRAND",
    }
    filter_string = ""

    try:

        if query_params:
            time_period = query_params.get('time-period')
            valid_time_periods = ["monthly", "quarterly", "half-yearly","yearly"]
            if time_period and time_period not in valid_time_periods:
                return {
                    "error": INVALID_TIME_PERIOD,
                    "message": f"'time-period' parameter must be one of {valid_time_periods} but got {time_period}",
                    "tileName": tile_name
                }
            
            filter_string = generate_global_filters_from_query_params(query_params, valid_filter_column_map)
        
        session = get_sf_session()
        raw_query = PowerBIReports.CHBK_PER_DAY.value
        query = text(raw_query.format(query_params=filter_string if filter_string else ""))
        query_placeholder_values = {
            "max_date": get_date_for_time_period('quarterly')
        }
        result = session.execute(query,query_placeholder_values)
        rows = result.fetchall()

        categories = []
        chargeback_data = []
        for row in rows:
            categories.append(row.date_key)  # currently this will be the first day of each month due to data limitations, can be updated to actual date when day level data is available
            chargeback_data.append(round(float(row.chbk)/1e6, 1) if row.chbk else 0)  # representation in millions with 1 decimal point
        
        tile_data = {
            "categories": categories,
            "series": [
                {
                    "name": "Chargeback",
                    "data": chargeback_data,
                    "type": "line",
                    "yAxis": 0
                }
            ]
        }

        return tile_data
    
    except Exception as e:
        logger.error(f"Error fetching chargeback per day data: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e),
            "tileName": tile_name
        }
    
    finally:
        if session:
            session.close()



def get_quarterly_dispense_purchase_comparison_by_corp_data(query_params: dict = None):
    """
    Fetch quarterly dispense vs purchase comparison data grouped by corporation for table visualization.
    
    Database View: vwDispenseVsPurchaseVolume
    
    This tile returns tabular data showing quarterly comparison of dispense and purchase
    volumes organized by L4 Corp Org Name, formatted using the new data structure format
    requested by the UI team for corporation grouping.
    
    Args:
        query_params: Optional dictionary of query parameters for filtering
            - brands: Filter by brand (optional, can support multiple values)
    
    Returns:
        Dictionary containing:
            - meta: Object with periodType and periods array
            - staticColumns: Array with org, state, total definitions
            - measures: Array with dispense, purchase, diff definitions
            - rows: Array with period-nested data structure grouped by L4 Corp Org Name
        On error, returns error object with "error", "message", and "tileName" fields.
    
    Implementation:
        Queries vwDispenseVsPurchaseVolume database view to fetch actual
        dispense and purchase volumes aggregated by L4 Corp Org Name and quarter.
        Transforms the database results into the nested data structure format requested by UI team.
    """
    tile_name = "quarterly-dispense-purchase-comparison-by-corp"
    session = None
    valid_filter_column_map = {
        "brands": "Brand",
        "states": "State"
    }
    filter_string = ""
    
    try:
        
        # Validate date parameters if provided
        if query_params:
            filter_string = generate_global_filters_from_query_params(query_params, valid_filter_column_map)
        
        # Query database view for quarterly data by corporation
        session = get_session()
        
        try:
            # Set a short timeout for this query to fail fast if view doesn't exist
            raw_query = OverviewPageCharts.PUR_VS_DISP_CORP.value
            query = text(raw_query.format(query_params=filter_string))  # No additional filters for now,
            query_placeholder_values = {
                "max_date": get_date_for_time_period('quarterly')
            }
            result = session.execute(query, query_placeholder_values).fetchall()
        except Exception as db_error:
            # View might not exist yet in database
            error_msg = str(db_error).lower()
            if ERROR_DOES_NOT_EXIST in error_msg or "unknown" in error_msg or "not found" in error_msg or "table" in error_msg:
                logger.warning(f"View vwDispenseVsPurchaseVolume does not exist in database yet: {db_error}")
                return {
                    "error": "View not deployed",
                    "message": "The database view vwDispenseVsPurchaseVolume has not been deployed yet. Please run the database migration to create this view.",
                    "tileName": tile_name
                }
            # Log the actual error for debugging
            logger.error(f"Database error querying vwDispenseVsPurchaseVolume: {db_error}")
            raise  # Re-raise if it's a different error
        
        # Handle no data case
        if not result:
            return {
                "error": NO_DATA_FOUND,
                "message": "No quarterly comparison data available",
                "tileName": tile_name
            }
        
        # Extract unique periods and sort them (most recent first)
        periods_set = set()
        for row in result:
            periods_set.add((row.period_id, row.period_label))
        
        periods = sorted(list(periods_set), key=lambda x: x[0], reverse=True)[:4]  # Last 4 quarters
        periods_list = [{"id": p[0], "label": p[1]} for p in periods]
        
        # Group data by organization
        org_data = {}
        for row in result:
            org_key = (row.org_name, row.state)
            if org_key not in org_data:
                org_data[org_key] = {
                    'org': row.org_name,
                    'state': row.state,
                    'periods': {},
                    'total': 0
                }
            
            period_id = row.period_id
            org_data[org_key]['periods'][period_id] = {
                'dispense': int(row.dispense_qty) if row.dispense_qty else 0,
                'purchase': int(row.purchase_qty) if row.purchase_qty else 0,
                'diff': int(row.diff_qty) if row.diff_qty else 0
            }
            org_data[org_key]['total'] += int(row.dispense_qty) if row.dispense_qty else 0
        
        # Convert to rows array with IDs
        rows = []
        for idx, (org_key, data) in enumerate(
            sorted(org_data.items(), key=lambda item: item[1]["total"], reverse=True),
            start=1):
            rows.append({
                'id': idx,
                'org': data['org'],
                'state': data['state'],
                'periods': data['periods'],
                'total': data['total']
            })
        
        # Return the new data structure format as requested by the UI team
        return {
            "meta": {
                "periodType": "quarter",
                "periods": periods_list
            },
            "staticColumns": [
                {"id": "org", "label": "L4 Corp Org Name"},
                {"id": "state", "label": "State"},
                {"id": "total", "label": "Total"}
            ],
            "measures": [
                {"id": "dispense", "label": "Dispense QTY (Sum)", "valueType": "number", "format": "compact"},
                {"id": "purchase", "label": "Purchase QTY (Sum)", "valueType": "number"},
                {"id": "diff", "label": "Purchase Dispense Diff", "valueType": "number", "format": "compact"}
            ],
            "rows": rows
        }
        
    except Exception as e:
        logger.error(f"Error fetching {tile_name} data: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e),
            "tileName": tile_name
        }
    finally:
        if session:
            session.close()


def get_quarterly_dispense_purchase_comparison_by_state_data(query_params: dict = None):
    """
    Fetch quarterly dispense vs purchase comparison data grouped by state for table visualization.
    
    Database View: vwDispenseVsPurchaseVolume
    
    This tile returns tabular data showing quarterly comparison of dispense and purchase
    volumes organized by State, formatted using the new data structure format
    requested by the UI team for state grouping.
    
    Args:
        query_params: Optional dictionary of query parameters for filtering
            - brands: Filter by brand (optional, can support multiple values)
            - states: Filter by state (optional, can support multiple values)
    
    Returns:
        Dictionary containing:
            - meta: Object with periodType and periods array
            - staticColumns: Array with state, total definitions
            - measures: Array with dispense, purchase, diff definitions
            - rows: Array with period-nested data structure grouped by State
        On error, returns error object with "error", "message", and "tileName" fields.
    
    Implementation:
        Queries vwDispenseVsPurchaseVolume database view to fetch actual
        dispense and purchase volumes aggregated by State and quarter.
        Transforms the database results into the nested data structure format requested by UI team.
    """
    tile_name = "quarterly-dispense-purchase-comparison-by-state"
    session = None
    valid_filter_column_map = {
        "brands": "Brand",
        "states" : "State"
    }
    filter_string = ""
    
    try:
        
        # Validate date parameters if provided
        if query_params:
            filter_string = generate_global_filters_from_query_params(query_params, valid_filter_column_map)
        
        
        # Query database view for quarterly data by state
        session = get_session()
        
        try:
            raw_query = OverviewPageCharts.PUR_VS_DISP_STATE.value
            query = text(raw_query.format(query_params=filter_string))  # No additional filters for
            query_placeholder_values = {
                "max_date": get_date_for_time_period('quarterly')
            }
            result = session.execute(query, query_placeholder_values).fetchall()
        except Exception as db_error:
            # View might not exist yet in database
            error_msg = str(db_error).lower()
            if ERROR_DOES_NOT_EXIST in error_msg or "unknown" in error_msg or "not found" in error_msg or "table" in error_msg:
                logger.warning(f"View vwDispenseVsPurchaseVolume does not exist in database yet: {db_error}")
                return {
                    "error": "View not deployed",
                    "message": "The database view vwDispenseVsPurchaseVolume has not been deployed yet. Please run the database migration to create this view.",
                    "tileName": tile_name
                }
            # Log the actual error for debugging
            logger.error(f"Database error querying vwDispenseVsPurchaseVolume: {db_error}")
            raise  # Re-raise if it's a different error
        
        # Handle no data case
        if not result:
            return {
                "error": NO_DATA_FOUND,
                "message": "No quarterly comparison data available",
                "tileName": tile_name
            }
        
        # Extract unique periods and sort them (most recent first)
        periods_set = set()
        for row in result:
            periods_set.add((row.period_id, row.period_label))

        periods = sorted(list(periods_set), key=lambda x: x[0], reverse=True)[:4]  # Last 4 quarters
        periods_list = [{"id": p[0], "label": p[1]} for p in periods]
        
        # Group data by state and organization
        state_data = {}
        for row in result:
            state_key = row.state
            if state_key not in state_data:
                state_data[state_key] = {
                    'state': row.state,
                    'periods': {},
                    'total': 0
                }
            
            period_id = row.period_id
            state_data[state_key]['periods'][period_id] = {
                'dispense': int(row.dispense_qty) if row.dispense_qty else 0,
                'purchase': int(row.purchase_qty) if row.purchase_qty else 0,
                'diff': int(row.diff_qty) if row.diff_qty else 0
            }
            state_data[state_key]['total'] += int(row.dispense_qty) if row.dispense_qty else 0
        
        # Convert to rows array with IDs
        rows = []
        for idx, (state_key, data) in enumerate(
            sorted(state_data.items(), key=lambda item: item[1]["total"], reverse=True),
            start=1):
            rows.append({
                'id': idx,
                'state': data['state'],
                'periods': data['periods'],
                'total': data['total']
            })
        
        # Return the new data structure format as requested by the UI team
        return {
            "meta": {
                "periodType": "quarter",
                "periods": periods_list
            },
            "staticColumns": [
                {"id": "state", "label": "State"},
                {"id": "total", "label": "Total"}
            ],
            "measures": [
                {"id": "dispense", "label": "Dispense QTY (Sum)", "valueType": "number", "format": "compact"},
                {"id": "purchase", "label": "Purchase QTY (Sum)", "valueType": "number"},
                {"id": "diff", "label": "Purchase Dispense Diff", "valueType": "number", "format": "compact"}
            ],
            "rows": rows
        }
        
    except Exception as e:
        logger.error(f"Error fetching {tile_name} data: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e),
            "tileName": tile_name
        }
    finally:
        if session:
            session.close()


def get_anomaly_kpis_data(query_params: dict = None):
    """
    Fetch anomaly KPI metrics for the All Anomalies page (v4 field names).
    
    Database Views (Composite Tile):
        - vwAnomalousTransactions
    
    Args:
        query_params: Optional dictionary of query parameters for filtering
            (Currently not implemented - will be added in future tasks)
    
    Returns:
        Dictionary with v4 camelCase keys containing KPI summary metrics.
        On error, returns error object with "error", "message", and "tileName" fields.
    """
    tile_name = "anomaly-kpis"
    session = None
    valid_filters = {
        "ANOMALY_ACCOUNT_COUNT" : {
            "brands": "Anomaly_Brand",
            "states": "State",
            "daysOpen": "DaysOpen",
            "customerTypes": "Entity_Type"
        },
        "ACTIVE_ANOMALIES" : {
            "brands": "Anomaly_Brand",
            "states": "State",
            "daysOpen": "DaysOpen",
            "customerTypes": "Entity_Type"
        },
        "RISK_EXPOSURE" : {
            "brands": "Anomaly_Brand",
            "states": "State",
            "daysOpen": "DaysOpen",
            "customerTypes": "Entity_Type"
        },
        "RISK_UNITS" : {
            "brands": "Anomaly_Brand",
            "states": "State",
            "daysOpen": "DaysOpen",
            "customerTypes": "Entity_Type"
        }
    }

    time_period = "quarterly" # default time period for this tile, can be made dynamic in future when time period filtering is implemented
    
    try:

        if query_params:
            
            time_period = query_params.get('time-period')
            valid_time_periods = ["quarterly", "monthly", "half-yearly","yearly"]
            if time_period and time_period not in valid_time_periods:
                return {
                    "error": INVALID_TIME_PERIOD,
                    "message": f"'time-period' parameter must be one of {valid_time_periods} but got {time_period}",
                    "tileName": tile_name
                }
            
        
        # Get database session
        session = get_session()
        result = {}
        current_period=""
        previous_period=""
        count=0

        for kpi in AllAnomaliesSummaryKPI:
            filter_string = ""
            logger.info(f"Querying KPI {kpi.name} for filters filters: {query_params}")

            # filter string generation
            filter_string = generate_global_filters_from_query_params(query_params, valid_filters.get(kpi.name, {}))

            query = text(kpi.value.format(query_params=filter_string if filter_string else ""))
            query_placeholder_values = {
                "time_period": time_period if query_params and query_params.get('time-period') else 'quarterly',
                "max_date": get_date_for_time_period(time_period if query_params and query_params.get('time-period') else 'quarterly')
            }

            rows = session.execute(query, query_placeholder_values).fetchall()
            if rows:
                if not current_period:
                    current_period=rows[0].TimePeriod

                if not previous_period and len(rows) > 1:
                    previous_period=rows[1].TimePeriod
                
                result[kpi.name] = {
                    "current_value": float(rows[0].value) if rows[0].value is not None else None,
                    "previous_value": float(rows[1].value) if len(rows) > 1 and rows[1].value is not None else None
                }
            
            else:
                logger.error(f"No data returned for KPI {kpi.name} with filters: {query_params}")
                count+=1
                result[kpi.name] = {
                    "current_value": None,
                    "previous_value": None
                }

        if count == len(AllAnomaliesSummaryKPI):
            return {
                "error": NO_DATA_FOUND,
                "message": NO_DATA_AVAILABLE_FOR_SPECIFIED_PARAMETERS,
                "tileName": tile_name
            }
        
        # Return response with v4 field names
        return {
            "currentPeriod": current_period,
            "prevPeriod": previous_period,
            "coveredEntities": result.get("ANOMALY_ACCOUNT_COUNT", {}).get("current_value",0),
            "coveredEntitiesCompareToPrevious": calculate_percentage_change(result.get("ANOMALY_ACCOUNT_COUNT", {}).get("current_value",0), result.get("ANOMALY_ACCOUNT_COUNT", {}).get("previous_value",0)),
            "activeAnomalies": result.get("ACTIVE_ANOMALIES", {}).get("current_value",0),
            "activeAnomaliesCompareToPrevious": calculate_percentage_change(result.get("ACTIVE_ANOMALIES", {}).get("current_value",0), result.get("ACTIVE_ANOMALIES", {}).get("previous_value",0)),
            "totalRiskCost": result.get("RISK_EXPOSURE", {}).get("current_value",0),
            "totalRiskCostCompareToPrevious": calculate_percentage_change(result.get("RISK_EXPOSURE", {}).get("current_value",0), result.get("RISK_EXPOSURE", {}).get("previous_value",0)),
            "totalRiskUnits": result.get("RISK_UNITS", {}).get("current_value",0),
            "totalRiskUnitsCompareToPrevious": calculate_percentage_change(result.get("RISK_UNITS", {}).get("current_value",0), result.get("RISK_UNITS", {}).get("previous_value",0))

        }
        
    except Exception as e:
        logger.error(f"Error fetching {tile_name} data: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": f"An unexpected error occurred: {str(e)}",
            "tileName": tile_name
        }
    finally:
        if session:
            session.close()


def get_340b_growth_by_drivers_data(query_params: dict = None):
    """
    Fetch 340B growth data showing counts across different actions.
    
    Database View: vwThreeFourtyBGrowthByDrivers
    
    This tile returns bar chart data showing counts for different 340B action
    statuses such as Closed, Letter Sent, Under Investigation, etc. Each bar
    represents one action status with its corresponding count value.
    
    Args:
        query_params: Optional dictionary of query parameters for filtering
            - from: Start date for filtering (optional, format: YYYY-MM-DD)
            - to: End date for filtering (optional, format: YYYY-MM-DD)
            - segment: Segment filter - "340B" or "non-340B" (optional)
    
    Returns:
        List of dictionaries, one object per bar chart element, each containing:
            - actions: Action status name (string) - e.g., "Closed", "Letter Sent"
            - value: Count for that action status (integer) - e.g., 342, 285
        
        Example return value:
        [
            {"actions": "Closed", "value": 342},
            {"actions": "Resolved (after letter)", "value": 285},
            {"actions": "Letter Sent", "value": 198},
            {"actions": "Open (Unread)", "value": 156},
            {"actions": "False Positive", "value": 124},
            {"actions": "Under Investigation", "value": 98},
            {"actions": "Under HRSA Audit", "value": 76},
            {"actions": "Under Internal Audit", "value": 54}
        ]
        
        On error, returns error object with "error", "message", and "tileName" fields.
    
    Implementation:
        Queries vwThreeFourtyBGrowthByDrivers view directly which provides
        counts for each 340B action status, ordered by value descending.
    """
    tile_name = "340b-growth-by-drivers"
    session = None
    valid_filter_column_map = {
        "states": "State",
        "brands": "Anomaly_Brand",
        "daysOpen": "DaysOpen",
        "customerTypes": "Entity_Type",
    }
    filter_string = ""
    
    try:
        # Validate query parameters if provided
        if query_params:
            
            filter_string = generate_global_filters_from_query_params(query_params, valid_filter_column_map)
        
        # Query the view directly with simple SELECT
        session = get_session()
        raw_query = AllAnomaliesPageCharts.GROWTH_BY_DRIVERS_340B.value
        query = text(raw_query.format(query_params=filter_string if filter_string else ""))
        result = session.execute(query).fetchall()
        
        # Handle no data case
        if not result:
            return {
                "error": NO_DATA_AVAILABLE,
                "message": THE_VIEW_RETURNED_NO_DATA,
                "tileName": tile_name
            }
        
        # Map view columns to response format (list of {"actions", "value"})
        response = [
            {
                "actions": row.actions,
                "value": row.value
            }
            for row in result
        ]
        
        return response
        
    except Exception as e:
        logger.error(f"Error fetching {tile_name} data: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e),
            "tileName": tile_name
        }
    finally:
        if session:
            session.close()




def get_anomaly_detail_kpis_data(query_params: dict = None):
    """
    Fetch additional anomaly detail KPI metrics for the bottom row of the All Anomalies page.
    
    Database Views (Composite Tile):
        - vwTotalAnomalies: Provides TotalAnomalies count
        - vwCriticalRisk: Provides CriticalRiskCount with previous period comparison
        - vwAnomaliesPendingAction: Provides UnreadCount (pending action)
        - vwLettersSent: Provides LettersSentCount with previous period comparison
    
    This tile returns key performance indicators including:
        - totalAnomalies: Total count of anomalies
        - criticalRisk: Count of critical risk anomalies  
        - pendingAction: Count of anomalies pending action
        - lettersSent: Count of letters sent (matches "Letters Sent" UI label)
    
    Args:
        query_params: Optional dictionary of query parameters for filtering
            - from: Start date for filtering (optional, format: YYYY-MM-DD)
            - to: End date for filtering (optional, format: YYYY-MM-DD)
            - segment: Segment filter - "340B" or "non-340B" (optional)
    
    Returns:
        Dictionary containing:
            - totalAnomalies: Total anomaly count
            - criticalRisk: Critical risk anomaly count
            - pendingAction: Pending action count
            - lettersSent: Count of letters sent
        On error, returns error object with "error", "message", and "tileName" fields.
    
    Implementation:
        Queries 4 database views directly:
        - vwTotalAnomalies: Total anomaly count
        - vwCriticalRisk: Critical risk count
        - vwAnomaliesPendingAction: Pending action count
        - vwLettersSent: Letters sent count
    """
    tile_name = "anomaly-detail-kpis"
    session = None
    
    try:
        # Independent of filter - might be implemented in future
        
        # Get database session
        session = get_session()
        
        # Query each view separately
        # View 1: vwTotalAnomalies - Total anomaly count
        total_anomalies_result = session.execute(text("""
            SELECT TotalAnomalies
            FROM vwTotalAnomalies
        """)).fetchone()
        
        # View 2: vwCriticalRisk - Critical risk count with previous period
        critical_risk_result = session.execute(text("""
            SELECT CriticalRiskCount
            FROM vwCriticalRisk
        """)).fetchone()
        
        # View 3: vwAnomaliesPendingAction - Pending action count
        pending_action_result = session.execute(text("""
            SELECT UnreadCount
            FROM vwAnomaliesPendingAction
        """)).fetchone()
        
        # View 4: vwLettersSent - Letters sent count with previous period
        letters_sent_result = session.execute(text("""
            SELECT LettersSentCount
            FROM vwLettersSent
        """)).fetchone()
        
        # Handle case where views return no data
        if not total_anomalies_result or not critical_risk_result or not pending_action_result or not letters_sent_result:
            return {
                "error": NO_DATA_AVAILABLE,
                "message": "One or more views returned no data",
                "tileName": tile_name
            }
        
        # Extract values from view results
        total_anomalies = total_anomalies_result.TotalAnomalies or 0
        critical_risk_current = critical_risk_result.CriticalRiskCount or 0
        pending_action = pending_action_result.UnreadCount or 0
        letters_sent_current = letters_sent_result.LettersSentCount or 0
        
        # Calculate percentage changes using helper function
        # Note: totalAnomalies and pendingAction don't have previous period data in views,
        # so we return "N/A" for their comparisons
        
        # Combine results from all 4 views
        return {
            "totalAnomalies": total_anomalies,
            "criticalRisk": critical_risk_current,
            "pendingAction": pending_action,
            "lettersSent": letters_sent_current
        }
        
    except Exception as e:
        logger.error(f"Error fetching {tile_name} data: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": f"An unexpected error occurred: {str(e)}",
            "tileName": tile_name
        }
    finally:
        if session:
            session.close()


def validate_dual_series_structure(tile_data: dict, tile_name: str) -> tuple[bool, dict]:
    """
    Validate dual-series data structure for dual-line chart tiles.
    
    Args:
        tile_data: The tile data dictionary to validate
        tile_name: Name of the tile for error reporting
    
    Returns:
        Tuple of (is_valid, error_response_or_empty_dict)
        - is_valid: True if structure is valid, False otherwise
        - error_response_or_empty_dict: Error response dict if invalid, empty dict if valid
    
    Validates:
        - Presence of 'categories' and 'series' fields
        - Series is a list with exactly 2 items for dual-line charts
        - Each series has required metadata fields (name, data, type, yAxis)
        - Both series have equal length data arrays
        - Categories length matches all series data lengths
        - Data arrays contain only numeric values (including zero/null handling)
        - yAxis values are 0 and 1 for dual Y-axis configuration
        - Data type consistency within each series
        - Specific error messages for each validation failure
    """
    if not isinstance(tile_data, dict):
        return False, create_error_response(
            "Invalid data structure",
            "Tile data must be a dictionary",
            tile_name
        )
    
    # Validate presence of required top-level fields
    if 'categories' not in tile_data:
        return False, create_error_response(
            "Missing categories field",
            "Dual-line chart data must include 'categories' field",
            tile_name
        )
    
    if 'series' not in tile_data:
        return False, create_error_response(
            "Missing series field",
            "Dual-line chart data must include 'series' field",
            tile_name
        )
    
    categories = tile_data['categories']
    series = tile_data['series']
    
    # Validate categories
    if not isinstance(categories, list):
        return False, create_error_response(
            "Invalid categories format",
            "Categories must be a list",
            tile_name
        )
    
    if len(categories) == 0:
        return False, create_error_response(
            "Empty categories",
            "Categories list cannot be empty",
            tile_name
        )
    
    # Validate series structure
    if not isinstance(series, list):
        return False, create_error_response(
            "Invalid series format",
            "Series must be a list",
            tile_name
        )
    
    if len(series) != 2:
        return False, create_error_response(
            "Invalid series count",
            f"Dual-line chart must have exactly 2 series, found {len(series)}",
            tile_name
        )
    
    # Validate each series
    required_fields = ['name', 'data', 'type', 'yAxis']
    expected_y_axes = {0, 1}
    found_y_axes = set()
    
    for i, series_item in enumerate(series):
        if not isinstance(series_item, dict):
            return False, create_error_response(
                "Invalid series item format",
                f"Series item {i} must be a dictionary",
                tile_name
            )
        
        # Check required fields
        for field in required_fields:
            if field not in series_item:
                return False, create_error_response(
                    "Missing series metadata",
                    f"Series item {i} missing required field '{field}'",
                    tile_name
                )
        
        # Validate series name
        if not isinstance(series_item['name'], str) or not series_item['name'].strip():
            return False, create_error_response(
                "Invalid series name",
                f"Series item {i} name must be a non-empty string",
                tile_name
            )
        
        # Validate series data
        data = series_item['data']
        if not isinstance(data, list):
            return False, create_error_response(
                "Invalid series data format",
                f"Series item {i} data must be a list",
                tile_name
            )
        
        # Validate data length matches categories
        if len(data) != len(categories):
            return False, create_error_response(
                "Data length mismatch",
                f"Series item {i} data length ({len(data)}) does not match categories length ({len(categories)})",
                tile_name
            )
        
        # Validate data contains only numeric values (including zero/null handling)
        for j, value in enumerate(data):
            # Handle null/None values gracefully by converting to 0
            if value is None:
                data[j] = 0
                logger.warning(f"Converted null value to 0 in series '{series_item['name']}' at index {j}")
                continue
            
            # Validate numeric types (int, float)
            if not isinstance(value, (int, float)):
                return False, create_error_response(
                    "Invalid data type",
                    f"Series '{series_item['name']}' contains non-numeric value at index {j}: expected number, found {type(value).__name__} ({value})",
                    tile_name
                )
            
            # Handle infinite or NaN values
            if isinstance(value, float):
                import math
                if math.isnan(value):
                    return False, create_error_response(
                        "Invalid data value",
                        f"Series '{series_item['name']}' contains NaN value at index {j}",
                        tile_name
                    )
                if math.isinf(value):
                    return False, create_error_response(
                        "Invalid data value",
                        f"Series '{series_item['name']}' contains infinite value at index {j}",
                        tile_name
                    )
            
            # Validate reasonable value ranges for volume data (millions of dollars)
            if 'Volume' in series_item['name'] and '$MM' in series_item['name']:
                if value < 0:
                    return False, create_error_response(
                        "Invalid volume data",
                        f"Series '{series_item['name']}' contains negative volume value at index {j}: {value}",
                        tile_name
                    )
                if value > 10000:  # Reasonable upper limit for $MM values
                    logger.warning(f"Unusually large volume value in series '{series_item['name']}' at index {j}: {value}")
            
            # Validate reasonable value ranges for anomaly count data
            if 'Anomalies' in series_item['name'] and 'Detected' in series_item['name']:
                if value < 0:
                    return False, create_error_response(
                        "Invalid anomaly count",
                        f"Series '{series_item['name']}' contains negative count value at index {j}: {value}",
                        tile_name
                    )
                # Allow both integers and floats for anomaly counts (some data sources may provide floats)
                # Just ensure the value is non-negative and reasonable
                if isinstance(value, float) and not (0 <= value <= 10000):
                    logger.warning(f"Unusually large anomaly count in series '{series_item['name']}' at index {j}: {value}")
                elif isinstance(value, int) and not (0 <= value <= 10000):
                    logger.warning(f"Unusually large anomaly count in series '{series_item['name']}' at index {j}: {value}")
        
        # Validate series type
        if not isinstance(series_item['type'], str) or series_item['type'] not in ['line', 'area']:
            return False, create_error_response(
                "Invalid series type",
                f"Series item {i} type must be 'line' or 'area'",
                tile_name
            )
        
        # Validate yAxis
        y_axis = series_item['yAxis']
        if not isinstance(y_axis, int) or y_axis not in [0, 1]:
            return False, create_error_response(
                "Invalid yAxis value",
                f"Series item {i} yAxis must be 0 or 1, found {y_axis}",
                tile_name
            )
        
        found_y_axes.add(y_axis)
    
    # Validate that both Y-axes are used (0 and 1)
    if found_y_axes != expected_y_axes:
        return False, create_error_response(
            "Incomplete yAxis configuration",
            f"Dual-line chart must use both yAxis 0 and 1, found {sorted(found_y_axes)}",
            tile_name
        )
    
    return True, {}


def validate_dual_series_data_consistency(tile_data: dict, tile_name: str) -> tuple[bool, dict]:
    """
    Validate data consistency within dual-series tiles.
    
    Args:
        tile_data: The tile data dictionary to validate
        tile_name: Name of the tile for error reporting
    
    Returns:
        Tuple of (is_valid, error_response_or_empty_dict)
        - is_valid: True if data is consistent, False otherwise
        - error_response_or_empty_dict: Error response dict if invalid, empty dict if valid
    
    Validates:
        - Series data arrays are not empty
        - Data type consistency within each series
        - Reasonable data ranges for specific metric types
        - No missing or corrupted data points
    """
    if not tile_data or 'series' not in tile_data:
        return False, create_error_response(
            "Missing series data",
            "Dual-series tile data is missing or corrupted",
            tile_name
        )
    
    series = tile_data['series']
    
    for i, series_item in enumerate(series):
        if not series_item or 'data' not in series_item:
            return False, create_error_response(
                "Missing series data",
                f"Series item {i} is missing data array",
                tile_name
            )
        
        data = series_item['data']
        series_name = series_item.get('name', f'Series {i}')
        
        # Check for empty data arrays
        if not data or len(data) == 0:
            return False, create_error_response(
                "Empty series data",
                f"Series '{series_name}' contains no data points",
                tile_name
            )
        
        # Validate data type consistency within series
        data_types = set(type(value).__name__ for value in data if value is not None)
        if len(data_types) > 2:  # Allow int and float together
            return False, create_error_response(
                "Inconsistent data types",
                f"Series '{series_name}' contains mixed data types: {', '.join(data_types)}",
                tile_name
            )
        
        # Check for all-zero data (potential data issue)
        non_zero_values = [v for v in data if v != 0 and v is not None]
        if len(non_zero_values) == 0:
            logger.warning(f"Series '{series_name}' contains only zero values - potential data issue")
    
    return True, {}


def handle_dual_series_error_scenarios(tile_data: dict, tile_name: str) -> tuple[bool, dict]:
    """
    Handle specific error scenarios for dual-series tiles.
    
    Args:
        tile_data: The tile data dictionary to validate
        tile_name: Name of the tile for error reporting
    
    Returns:
        Tuple of (is_valid, error_response_or_empty_dict)
        - is_valid: True if no critical errors, False otherwise
        - error_response_or_empty_dict: Error response dict if critical error, empty dict if valid
    
    Handles:
        - Missing series metadata
        - Corrupted data structures
        - Invalid series configurations
        - Data format inconsistencies
    """
    try:
        # Check for completely missing tile data
        if tile_data is None:
            return False, create_error_response(
                "Tile data not found",
                f"No data available for tile '{tile_name}'",
                tile_name
            )
        
        # Check for corrupted data structure
        if not isinstance(tile_data, dict):
            return False, create_error_response(
                "Corrupted tile data",
                f"Tile data for '{tile_name}' is not in expected format",
                tile_name
            )
        
        # Validate required dual-series structure
        structure_valid, structure_error = validate_dual_series_structure(tile_data, tile_name)
        if not structure_valid:
            return False, structure_error
        
        # Validate data consistency
        consistency_valid, consistency_error = validate_dual_series_data_consistency(tile_data, tile_name)
        if not consistency_valid:
            return False, consistency_error
        
        return True, {}
        
    except Exception as e:
        logger.error(f"Error during dual-series validation for {tile_name}: {e}")
        return False, create_error_response(
            "Validation error",
            f"Failed to validate dual-series data for '{tile_name}': {str(e)}",
            tile_name
        )


def validate_dual_series_batch_compatibility(tile_data: dict, tile_name: str, all_requested_tiles: list) -> tuple[bool, dict]:
    """
    Validate dual-series tiles for batch request compatibility.
    
    Args:
        tile_data: The tile data dictionary to validate
        tile_name: Name of the tile for error reporting
        all_requested_tiles: List of all tiles requested in the batch
    
    Returns:
        Tuple of (is_valid, error_response_or_empty_dict)
        - is_valid: True if compatible with batch request, False otherwise
        - error_response_or_empty_dict: Error response dict if invalid, empty dict if valid
    
    Validates:
        - Dual-series tiles work correctly alongside single-series tiles
        - No performance degradation in batch processing
        - Consistent response format across all tiles in batch
    """
    try:
        # Validate basic dual-series structure
        structure_valid, structure_error = validate_dual_series_structure(tile_data, tile_name)
        if not structure_valid:
            return False, structure_error
        
        # Check for potential performance issues with large batch requests
        if len(all_requested_tiles) > 10:
            logger.warning(f"Large batch request with {len(all_requested_tiles)} tiles including dual-series tile '{tile_name}' - potential performance impact")
        
        # Validate that dual-series data doesn't conflict with other tiles
        # (This is mainly a structural check - actual conflicts would be frontend-specific)
        if 'series' in tile_data and len(tile_data['series']) == 2:
            # Ensure both series have consistent structure for batch processing
            for i, series in enumerate(tile_data['series']):
                if not isinstance(series, dict):
                    return False, create_error_response(
                        "Batch compatibility error",
                        f"Dual-series tile '{tile_name}' has invalid series structure for batch processing",
                        tile_name
                    )
                
                # Check for required fields that frontend expects in batch responses
                required_batch_fields = ['name', 'data']
                for field in required_batch_fields:
                    if field not in series:
                        return False, create_error_response(
                            "Batch compatibility error",
                            f"Dual-series tile '{tile_name}' missing required field '{field}' for batch processing",
                            tile_name
                        )
        
        return True, {}
        
    except Exception as e:
        logger.error(f"Error validating batch compatibility for dual-series tile {tile_name}: {e}")
        return False, create_error_response(
            "Batch validation error",
            f"Failed to validate batch compatibility for dual-series tile '{tile_name}': {str(e)}",
            tile_name
        )


def get_anomalous_transactions_data(query_params: dict = None):
    """
    Fetch anomalous transactions data for dual-line chart visualization.
    
    Database View: vwAnomaliesTransactions
    
    This tile returns time series data showing both anomaly count and volume data over time,
    formatted for a dual-line chart visualization on the All Anomalies page.
    
    Args:
        query_params: Optional dictionary of query parameters for filtering
            - from: Start date for filtering (optional, format: YYYY-MM-DD)
            - to: End date for filtering (optional, format: YYYY-MM-DD)
            - segment: Segment filter - "340B" or "non-340B" (optional)
    
    Returns:
        Dictionary containing:
            - categories: List of time periods (months)
            - series: List with exactly 2 series for dual-line visualization:
                     1. "340B Anomalies Detected" (yAxis: 0)
                     2. "340B Volume ($MM)" (yAxis: 1)
        On error, returns error object with "error", "message", and "tileName" fields.
    
    Implementation:
        Queries vwAnomaliesTransactions view directly which provides monthly aggregated data
        for the last 12 months. The view returns YearMonth, AnomalyCount, and TotalChargeBack.
    """
    tile_name = "anomalous-transactions"
    session = None
    valid_filter_column_map = {
        "brands": "Anomaly_Brand",
        "states": "State",
        "daysOpen": "DaysOpen",
        "customerTypes": "Entity_Type"
    }

    filter_string = ""
    
    try:
        # Validate query parameters
        if query_params:
            
            time_period = query_params.get('time-period')
            valid_time_periods = ["monthly", "quarterly", "half-yearly","yearly"]
            if time_period not in valid_time_periods:
                return create_error_response(
                    INVALID_TIME_PERIOD,
                    f"Time period '{time_period}' is not valid. Valid options are: {', '.join(valid_time_periods)}",
                    tile_name
                )
            
            filter_string = generate_global_filters_from_query_params(query_params, valid_filter_column_map)
        
        # Get database session
        session = get_session()
        raw_query = AllAnomaliesPageCharts.ANOMALOUS_TRANSACTIONS.value
        query = text(raw_query.format(query_params=filter_string))
        query_placeholder_values = {
            "time_period": time_period if query_params and query_params.get('time-period') else 'quarterly',
            "max_date": get_date_for_time_period(time_period if query_params and query_params.get('time-period') else 'quarterly')
        }
        # Query the view directly with simple SELECT
        result = session.execute(query, query_placeholder_values).fetchall()
        
        # Handle no data case
        if not result:
            logger.warning(f"No data returned from vwAnomaliesTransactions for {tile_name} with filters: {query_params}")
            # Return empty structure with 12 months of zeros
            return {
                "categories": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
                "series": [
                    {
                        "name": "340B Anomalies Detected",
                        "data": [0] * 12,
                        "type": "area",
                        "yAxis": 0
                    },
                    {
                        "name": "340B Volume ($MM)",
                        "data": [0] * 12,
                        "type": "area",
                        "yAxis": 1
                    }
                ],
                "error": NO_DATA_AVAILABLE,
            }
        
        # Process results and format for dual-series chart
        categories = []
        anomaly_counts = []
        volume_amounts = []
        for row in result:
            # Extract and format YearMonth into readable month format (e.g., "Jan '23")
            categories.append(row.TimePeriod)
            anomaly_counts.append(row.anomaly_count or 0)  # Handle nulls by converting to 0
            volume_amounts.append(float(row.chargeback)/1e6 if row.chargeback else 0) # Handle nulls and ensure float type for volume in millions of dollars
        
        # Format as dual-series chart data
        chart_data = {
            "categories": categories,
            "series": [
                {
                    "name": "340B Anomalies Detected",
                    "data": anomaly_counts,
                    "type": "area",
                    "yAxis": 0
                },
                {
                    "name": "340B Volume ($MM)",
                    "data": volume_amounts,
                    "type": "area",
                    "yAxis": 1
                }
            ]
        }
        
        return chart_data
        
    except Exception as e:
        logger.error(f"Error fetching {tile_name} data: {e}")
        return create_error_response(
            INTERNAL_SERVER_ERROR,
            str(e),
            tile_name
        )
    finally:
        if session:
            session.close()


def get_anomalies_confidence_accounts_data(query_params: dict = None):
    """
    Fetch anomalies by confidence score for accounts as donut chart data.
    
    Database View: vwAnomaliesConfidenceAccounts
    
    This tile returns donut chart data showing the distribution of anomalies by confidence score
    for accounts, formatted for donut chart visualization on the All Anomalies page.
    
    Args:
        query_params: Optional dictionary of query parameters for filtering
            - from: Start date for filtering (optional, format: YYYY-MM-DD)
            - to: End date for filtering (optional, format: YYYY-MM-DD)
            - segment: Segment filter - "340B" or "non-340B" (optional)
    
    Returns:
        Dictionary containing:
            - series: List with single series containing confidence score distribution
                     (High, Medium, Low categories with counts)
        On error, returns error object with "error", "message", and "tileName" fields.
    
    Implementation:
        Queries vwAnomaliesConfidenceAccounts view directly which provides
        confidence score distribution data in donut chart format.
    """
    tile_name = "anomalies-confidence-accounts"
    session = None
    valid_filter_column_map = {
        "brands": "Anomaly_Brand",
        "states": "State",
        "daysOpen": "DaysOpen",
        "customerTypes": "Entity_Type"
    }
    filter_string = ""
    
    try:
        
        # Validate query parameters
        if query_params:
            is_valid, error_response = validate_query_parameters(query_params, tile_name)
            if not is_valid:
                return error_response
            
            filter_string = generate_global_filters_from_query_params(query_params, valid_filter_column_map)
        
        # Query the view directly
        session = get_session()
        raw_query = AllAnomaliesPageCharts.ANOMALIES_BY_SCORE_ACCOUNTS.value
        query = text(raw_query.format(query_params=filter_string))
        result = session.execute(query).fetchall()
        
        # Handle no data case
        if not result:
            return {
                "error": NO_DATA_AVAILABLE,
                "message": THE_VIEW_RETURNED_NO_DATA,
                "tileName": tile_name
            }
        
        # Format response as donut chart data
        donut_data = {
            "series": [
                {
                    "name": "Confidence Score",
                    "data": [
                        {"name": row.name, "y": row.count}
                        for row in result
                    ]
                }
            ]
        }
        
        return donut_data
        
    except Exception as e:
        logger.error(f"Error fetching {tile_name} data: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e),
            "tileName": tile_name
        }
    finally:
        if session:
            session.close()



def get_anomalies_score_growth_data(query_params: dict = None):
    """
    Fetch anomalies chargeback growth data for the All Anomalies page, based on the priority score.

    Database View: vwAnomaliesScoreGrowth
    
    This tile returns data showing the growth rate of anomalies over time,
    formatted for visualization on the All Anomalies page.
    
    Args:
        query_params: Optional dictionary of query parameters for filtering
            - brands: Comma-separated list of brands to filter by (optional)
            - state: Comma-separated list of states to filter by (optional)
            - daysOpen: Comma-separated list of days open ranges to filter by (optional)
            - time-period: Time period for growth calculation - "monthly", "quarterly", "half-yearly", "yearly" (optional, default: "quarterly")
    
    Returns:
        Dictionary containing:
            - series: List with single series containing growth rate data
                     (currentPeriod, previousPeriod, and growth rate)
        On error, returns error object with "error", "message", and "tileName" fields.
    """
    tile_name = "anomalies-score-growth"
    session = None
    
    valid_filter_column_map = {
        "brands": "Anomaly_Brand",
        "states": "State",
        "daysOpen": "DaysOpen",
        "customerTypes": "Entity_Type"
    }
    filter_string = ""
    
    try:

        def _get_curr_prev_timeperiod(max_date,timeperiod=None):

            error_response = None

            if max_date is None:
                logger.warning(f"Missing max_date parameter for time period calculation in {tile_name}")
                error_response = {
                    "error": "Missing max_date parameter",
                    "message": "max_date query parameter is required for time period calculation",
                    "tileName": tile_name
                }
                return None, None, error_response
            date_obj = datetime.strptime(max_date,"%Y-%m-%d")
            prev_period = None
            curr_period = None

            if timeperiod == 'quarterly':
                month_diff=3
                curr_period = f"Q{(date_obj.month-1)//3+1}'{date_obj.strftime('%y')}"
                prev_date_obj = date_obj - relativedelta(months=month_diff)
                prev_period = f"Q{(prev_date_obj.month-1)//3+1}'{prev_date_obj.strftime('%y')}"

            elif timeperiod == 'monthly':
                month_diff = 1
                curr_period = f"""{date_obj.strftime("%b'%y")}"""
                prev_date_obj = date_obj - relativedelta(months=month_diff)
                prev_period = f"""{prev_date_obj.strftime("%b'%y")}"""

            elif timeperiod == 'half-yearly':
                month_diff = 6
                if date_obj.month >= 6:
                    period_prefix="H2"
                else:
                    period_prefix="H1"

                curr_period = f"{period_prefix}'{date_obj.strftime('%y')}"
                prev_date_obj = date_obj - relativedelta(months=month_diff)

                if prev_date_obj.month >= 6:
                    period_prefix="H2"
                else:
                    period_prefix="H1"
                prev_period = f"{period_prefix}'{prev_date_obj.strftime('%y')}"
                

            elif timeperiod == 'yearly':
                month_diff = 12

                curr_period = date_obj.strftime("%Y")
                prev_date_obj = date_obj - relativedelta(months=month_diff)
                prev_period = prev_date_obj.strftime("%Y")

            else:
                logger.warning(f"Invalid or missing time period parameter: {timeperiod}")
                error_response = {
                    "error": INVALID_TIME_PERIOD,
                    "message": "Time period parameter must be one of: monthly, quarterly, half-yearly, yearly",
                    "tileName": tile_name
                }
                return None, None, error_response

            return curr_period, prev_period, None
        
        # Validate query parameters
        if query_params:
            
            time_period = query_params.get('time-period',"quarterly")
            if time_period:
                max_date = get_date_for_time_period(time_period if query_params and query_params.get('time-period') else 'quarterly')
                curr_period, prev_period, error_response = _get_curr_prev_timeperiod(max_date, time_period)
                if error_response:
                    return error_response
            
            filter_string = generate_global_filters_from_query_params(query_params, valid_filter_column_map)
        
        # Query the view directly
        session = get_session()
        raw_query = AllAnomaliesPageCharts.ANOMALIES_BY_SCORE_GROWTH.value
        query = text(raw_query.format(query_params=filter_string))
        query_placeholder_values = {
            "time_period": time_period,
            "max_date": max_date
        }
        result = session.execute(query, query_placeholder_values).fetchall()
        
        # Handle no data case
        if not result:
            return {
                "error": NO_DATA_AVAILABLE,
                "message": THE_VIEW_RETURNED_NO_DATA,
                "tileName": tile_name,
                "currentPeriod": curr_period,
                "previousPeriod": prev_period
            }

        score_list = []
        if result:
            for score_row in result:
                score_list.append({
                "name": score_row.name,
                "desc": score_row.desc,
                "y": round(((score_row.curr_chargeback - score_row.prev_chargeback) / score_row.prev_chargeback) * 100, 1) if score_row.prev_chargeback else None,
                "currentPeriod": curr_period,
                "previousPeriod": prev_period
            })  

        return score_list
        
    except Exception as e:
        logger.error(f"Error fetching {tile_name} data: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e),
            "tileName": tile_name
        }
    finally:
        if session:
            session.close()

def get_anomalies_confidence_growth_data(query_params: dict = None):
    """
    Fetch anomalies by confidence score for growth as donut chart data.
    
    Database View: vwAnomaliesConfidenceGrowth
    
    This tile returns donut chart data showing the distribution of anomalies by confidence score
    for growth metrics, formatted for donut chart visualization on the All Anomalies page.
    
    Args:
        query_params: Optional dictionary of query parameters for filtering
            - from: Start date for filtering (optional, format: YYYY-MM-DD)
            - to: End date for filtering (optional, format: YYYY-MM-DD)
            - segment: Segment filter - "340B" or "non-340B" (optional)
    
    Returns:
        Dictionary containing:
            - series: List with single series containing growth rate distribution
                     (High, Medium, Low categories with counts)
        On error, returns error object with "error", "message", and "tileName" fields.
    
    Implementation:
        Queries vwAnomaliesConfidenceGrowth view directly which provides
        growth rate distribution data in donut chart format.
    """
    tile_name = "anomalies-confidence-growth"
    session = None
    
    try:
        # Validate query parameters
        if query_params:
            is_valid, error_response = validate_query_parameters(query_params, tile_name)
            if not is_valid:
                return error_response
        
        # Query the view directly
        session = get_session()
        result = session.execute(text("""
            SELECT
                name,
                y
            FROM vwAnomaliesConfidenceGrowth
        """)).fetchall()
        
        # Handle no data case
        if not result:
            return {
                "error": NO_DATA_AVAILABLE,
                "message": THE_VIEW_RETURNED_NO_DATA,
                "tileName": tile_name
            }
        
        # Format response as donut chart data
        donut_data = {
            "series": [
                {
                    "name": "Growth Rate",
                    "data": [
                        {"name": row.name, "y": row.y}
                        for row in result
                    ]
                }
            ]
        }
        
        return donut_data
        
    except Exception as e:
        logger.error(f"Error fetching {tile_name} data: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e),
            "tileName": tile_name
        }
    finally:
        if session:
            session.close()



def get_anomalous_transaction_map_chargeback_data(query_params: dict = None):
    """
    Fetch anomalous transaction map data showing geographic distribution of chargeback quantities.
    
    Database View: vwAnomalousTransactionMapChargeback
    
    This tile returns geographic map data showing anomalous transactions across US cities
    with chargeback quantity values for map visualization on the All Anomalies page.
    
    Args:
        query_params: Optional dictionary of query parameters for filtering
            - brands: Comma-separated list of brands to filter by (optional)
            - state: Comma-separated list of states to filter by (optional)
            - daysOpen: Comma-separated list of days open ranges to filter by (optional)
    
    Returns:
        List of dictionaries containing:
            - name: City and state name (e.g., "New York, NY")
            - lat: Latitude coordinate
            - lon: Longitude coordinate
            - value: Chargeback quantity value
            - size: Size indicator for map visualization ("small", "medium", "large")
        On error, returns error object with "error", "message", and "tileName" fields.
    
    Implementation:
        Queries vwAnomalousTransactionMapChargeback view directly which aggregates
        chargeback amounts by city with geographic coordinates and size categorization.
    """
    tile_name = "anomalous-transaction-map-chargeback"
    session = None
    valid_filter_column_map = {
        "brands": "Anomaly_Brand",
        "states": "State",
        "daysOpen": "DaysOpen",
        "customerTypes": "Entity_Type"
    }
    filter_string = ""
    
    try:
        # Validate query parameters if provided
        if query_params:
            
            filter_string = generate_global_filters_from_query_params(query_params, valid_filter_column_map)
        
        # Query the view directly
        session = get_session()
        raw_query = AllAnomaliesPageCharts.ANOMALY_CHARGEBACK_MAP.value
        query = text(raw_query.format(query_params=filter_string))
        result = session.execute(query).fetchall()
        
        # Handle no data case
        if not result:
            return {
                "error": NO_DATA_AVAILABLE,
                "message": THE_VIEW_RETURNED_NO_DATA,
                "tileName": tile_name
            }
        
        # Map view columns to response format
        map_data = []
        for row in result:
            map_data.append({
                "name": row.name,
                "lat": float(row.lat) if row.lat is not None else 0.0,
                "lon": float(row.lon) if row.lon is not None else 0.0,
                "value": float(row.value) if row.value is not None else 0.0,
                "size": row.size
            })
        
        return map_data
        
    except Exception as e:
        logger.error(f"Error fetching {tile_name} data: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e),
            "tileName": tile_name
        }
    finally:
        if session:
            session.close()


def get_anomalous_transaction_map_priority_data(query_params: dict = None):
    """
    Fetch anomalous transaction map data showing geographic distribution of priority scores.
    
    Database View: vwAnomalousTransactionMapPriority
    
    This tile returns geographic map data showing anomalous transactions across US cities
    with priority score values for map visualization on the All Anomalies page.
    
    Args:
        query_params: Optional dictionary of query parameters for filtering
            - brands: Comma-separated list of brands to filter by (optional)
            - state: Comma-separated list of states to filter by (optional)
            - daysOpen: Comma-separated list of days open ranges to filter by (optional)
    
    Returns:
        List of dictionaries containing:
            - name: City and state name (e.g., "Miami, FL")
            - lat: Latitude coordinate
            - lon: Longitude coordinate
            - value: Priority score value
            - size: Size indicator for map visualization ("small", "medium", "large")
        On error, returns error object with "error", "message", and "tileName" fields.
    
    Implementation:
        Queries vwAnomalousTransactionMapPriority view directly which aggregates
        priority scores (linkage scores) by city with geographic coordinates and size categorization.
    """
    tile_name = "anomalous-transaction-map-priority"
    session = None
    valid_filter_column_map = {
        "brands": "Anomaly_Brand",
        "states": "State",
        "daysOpen": "DaysOpen",
        "customerTypes": "Entity_Type"
    }
    filter_string = ""
    
    try:
        # Validate query parameters if provided
        if query_params:
            
            filter_string = generate_global_filters_from_query_params(query_params, valid_filter_column_map)
        
        # Query the view directly
        session = get_session()
        raw_query = AllAnomaliesPageCharts.ANOMALY_PRIORITY_MAP.value
        query = text(raw_query.format(query_params=filter_string))
        result = session.execute(query).fetchall()
        
        # Handle no data case
        if not result:
            return {
                "error": NO_DATA_AVAILABLE,
                "message": THE_VIEW_RETURNED_NO_DATA,
                "tileName": tile_name
            }
        
        # Map view columns to response format
        map_data = []
        for row in result:
            map_data.append({
                "name": row.name,
                "lat": float(row.lat) if row.lat is not None else 0.0,
                "lon": float(row.lon) if row.lon is not None else 0.0,
                "value": float(row.value) if row.value is not None else 0.0,
                "size": row.size
            })
        
        return map_data
        
    except Exception as e:
        logger.error(f"Error fetching {tile_name} data: {e}")
        return {
            "error": INTERNAL_SERVER_ERROR,
            "message": str(e),
            "tileName": tile_name
        }
    finally:
        if session:
            session.close()


def get_account_detail_header_data(query_params: dict = None):
    """
    Fetch basic account information for the account-detail-header tile.
    
    Database View: vwAccountDetailHeader
    
    This tile returns account name, full address, and account ID for a specific account.
    Either 340bId OR pharmacyId parameter is REQUIRED for this tile (exactly one must be provided).
    
    Args:
        query_params: Dictionary of query parameters
            - 340bId (required if pharmacyId not provided): The 340B covered entity ID to retrieve
            - pharmacyId (required if 340bId not provided): The contract pharmacy ID to retrieve
    
    Returns:
        Dictionary containing:
            - accountName: Name of the account (string)
            - address: Full address formatted as single string (string)
            - 340bId or pharmacyId: The account ID (string) - field name depends on which parameter was provided
        On error, returns error object with "error", "message", and "tileName" fields.
    
    Implementation:
        Queries vwAccountDetailHeader view directly using simple SELECT statement
        with accountId filter. The view handles address formatting and supports both
        340B covered entities and contract pharmacy accounts via UNION.
    
    Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 7.4, 8.1, 8.2, 8.3, 10.1, 10.2
    """
    tile_name = "account-detail-header"
    session = None
    
    try:
        # STEP 1: Validate that exactly one of 340bId or pharmacyId is provided
        is_valid, error_response, id_type, id_value = validate_account_id_parameters(query_params, tile_name)
        if not is_valid:
            return error_response
        
        # STEP 2: Query database view with accountId filter
        session = get_session()
        
        # Query the view with accountId filter
        if id_type == "340B":
            query = text("SELECT accountName, address, accountId FROM vwAccountDetailHeader WHERE `accountId` = :accountId")
        else:  # Pharmacy
            query = text("SELECT accountName, address, accountId FROM vwPharmacyDetailHeader WHERE `accountId` = :accountId")

        result = session.execute(query, {"accountId": id_value}).fetchone()
        
        # STEP 3: Handle no data found scenario
        if result is None:
            return {
                "error": NO_DATA_FOUND,
                "message": f"No account found with the specified {'340bId' if id_type == '340B' else 'pharmacyId'}",
                "tileName": tile_name
            }
        
        # STEP 4: Return accountName, address, and appropriate ID field
        response = {
            "accountName": result.accountName or "",
            "address": result.address or ""
        }
        
        # Add the appropriate ID field based on which parameter was provided
        if id_type == "340B":
            response["340bId"] = result.accountId or id_value
        else:
            response["pharmacyId"] = result.accountId or id_value
        
        return response
        
    except ValueError as e:
        # Handle validation errors
        logger.error(f"Validation error in {tile_name}: {e}")
        return {
            "error": INVALID_PARAMS,
            "message": str(e),
            "tileName": tile_name
        }
    except Exception as e:
        # Handle unexpected errors
        logger.error(f"Unexpected error fetching {tile_name} data: {e}")
        
        # Check for specific error types
        error_message = str(e).lower()
        if ERROR_DOES_NOT_EXIST in error_message or ERROR_UNKNOWN_TABLE in error_message:
            return {
                "error": VIEW_NOT_FOUND,
                "message": "Database view vwAccountDetailHeader does not exist",
                "tileName": tile_name
            }
        elif "connection" in error_message or "connect" in error_message:
            return {
                "error": CONNECTION_FAILED,
                "message": ERROR_CONNECTION,
                "tileName": tile_name
            }
        else:
            return {
                "error": INTERNAL_SERVER_ERROR,
                "message": f"An unexpected error occurred: {str(e)}",
                "tileName": tile_name
            }
    finally:
        # Always close the session
        if session:
            session.close()


def get_account_detail_kpis_data(query_params: dict = None):
    """
    Fetch KPI metrics for a specific account for the account-detail-kpis tile.
    
    Database View: vwAccountDetailKpis
    
    This tile returns three KPI metrics (Total Anomalies, Total WAC, Total Chargebacks)
    with period-over-period comparison values for a specific account.
    Either 340bId OR pharmacyId parameter is REQUIRED for this tile (exactly one must be provided).
    
    Args:
        query_params: Dictionary of query parameters
            - 340bId (required if pharmacyId not provided): The 340B covered entity ID to retrieve
            - pharmacyId (required if 340bId not provided): The contract pharmacy ID to retrieve
            - from (optional): Start date for filtering (format: YYYY-MM-DD)
            - to (optional): End date for filtering (format: YYYY-MM-DD)
    
    Returns:
        Dictionary containing:
            - totalAnomalies: Count of anomalies (integer)
            - totalAnomaliesCompareToPrevious: Percentage change from previous period (string with +/- prefix)
            - totalWAC: Total WAC amount formatted with K/M suffix (string)
            - totalWACCompareToPrevious: Percentage change from previous period (string with +/- prefix)
            - totalChargebacks: Total chargeback amount formatted with K/M suffix (string)
            - totalChargebacksCompareToPrevious: Percentage change from previous period (string with +/- prefix)
        On error, returns error object with "error", "message", and "tileName" fields.
    
    Implementation:
        Queries vwAccountDetailKpis view directly using simple SELECT statement
        with accountId filter. The view handles all complex SQL logic including
        period-over-period calculations. Lambda formats monetary values and
        comparison values using helper functions.
    
    Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 7.4, 8.1, 8.2, 10.1, 10.2, 10.3
    """
    tile_name = "account-detail-kpis"
    session = None
    valid_filter_column_map = {
        "TOT_ANOMALIES" : {
            "brands": "Anomaly_Brand",
            "state": "State",
        },
        "TOT_WAC_SALES" : {
            "brands": "Brand",
            "state": "State",
        },
        "TOT_CHBK" : {
            "brands": "Brand",
            "state": "State",
        }
    }
    time_period = 'quarterly'  # Default time period for comparison if not provided in query parameters
    
    try:
        # STEP 1: Validate that exactly one of 340bId or pharmacyId is provided
        is_valid, error_response, id_type, id_value = validate_account_id_parameters(query_params, tile_name)
        if not is_valid:
            return error_response
        
        if query_params:
            # STEP 2: Validate optional date parameters (from, to) and build filters
            is_valid, error_response = validate_query_parameters(query_params, tile_name)
            if not is_valid:
                return error_response
            time_period = query_params.get('time-period', time_period)
        
        session = get_session()
        # Query the view with accountId filter
        if id_type == "340B":
            template = AccountDetailsKPI
        else:  # Pharmacy
            template = PharmacyDetailsKPI

        query_placeholder_values = {
            "account_id": id_value,
            "time_period": time_period,
            "max_date": get_date_for_time_period(time_period)
        }
        count = 0
        result = {}
        current_period = None
        previous_period = None
        no_data_str="No data available for the specified parameters for the KPIs"
        for kpi in template:
            row = process_summary_kpis(kpi.value, query_params, session, tile_name, valid_filter_column_map.get(kpi.name,{}), query_placeholder_values)
            # Check if process_summary_kpis returned an error
            if "error" in row:
                return row
            
            result[kpi.name] = { "current_value": row.get("current_value", 0), "previous_value": row.get("previous_value", 0) }

            current_period = row.get("current_period", current_period)
            previous_period = row.get("previous_period", previous_period)
            
            if "no_data" in row:
                logger.warning(f"No data returned for KPI {kpi.name} in {tile_name}")
                count += 1
                no_data_str = no_data_str + f" {kpi.name},"

        if count == len(template):
            return {
                "error": NO_DATA_FOUND,
                "message": NO_DATA_AVAILABLE_FOR_SPECIFIED_PARAMETERS,
                "tileName": tile_name
            }
        
        return {
            "totalAnomalies": result.get("TOT_ANOMALIES", {}).get("current_value", 0),
            "totalAnomaliesCompareToPrevious": calculate_percentage_change(
                result.get("TOT_ANOMALIES", {}).get("current_value"),
                result.get("TOT_ANOMALIES", {}).get("previous_value")
            ),
            "totalWAC": result.get("TOT_WAC_SALES", {}).get("current_value",0),
            "totalWACCompareToPrevious": calculate_percentage_change(
                result.get("TOT_WAC_SALES", {}).get("current_value"),
                result.get("TOT_WAC_SALES", {}).get("previous_value")
            ),
            "totalChargebacks": result.get("TOT_CHBK", {}).get("current_value",0),
            "totalChargebacksCompareToPrevious": calculate_percentage_change(
                result.get("TOT_CHBK", {}).get("current_value"),
                result.get("TOT_CHBK", {}).get("previous_value")
            ),
             "currentPeriod": current_period,
             "previousPeriod": previous_period,
             "nodataResponse": no_data_str if count > 0 else None
        }
        
    except ValueError as e:
        # Handle validation errors
        logger.error(f"Validation error in {tile_name}: {e}")
        return {
            "error": INVALID_PARAMS,
            "message": str(e),
            "tileName": tile_name
        }
    except Exception as e:
        # Handle unexpected errors
        logger.error(f"Unexpected error fetching {tile_name} data: {e}")
        return _classify_database_error(e, tile_name, "vwAnomalousTransactions /  340B_ProcessedData",is_view=True)
        
    finally:
        # Always close the session
        if session:
            session.close()


def get_account_detail_anomalous_transactions_volume_data(query_params: dict = None):
    """
    Fetch anomalous transaction volume over time for a specific account for the account-detail-anomalous-transactions-volume tile.
    
    Database View: vwAnomalousTransactions
    
    This tile returns monthly transaction volume data for a specific account in a stacked area chart format.
    Either 340bId OR pharmacyId parameter is REQUIRED for this tile (exactly one must be provided).
    
    Args:
        query_params: Dictionary of query parameters
            - 340bId (required if pharmacyId not provided): The 340B covered entity ID
            - pharmacyId (required if 340bId not provided): The pharmacy ID
            - brands: Comma-separated list of brands to filter by (optional)
            - time-period: Time period for filtering - "monthly", "quarterly", "half
    
    Returns:
        Dictionary containing:
            - categories: List of month abbreviations (Jan, Feb, Mar, etc.)
            - series: List with exactly 1 series for stacked area chart:
                     "Transaction Volume" (yAxis: 0)
        On error, returns error object with "error", "message", and "tileName" fields.
    
    Implementation:
        Queries vwAnomalousTransactions view directly using simple SELECT statement
        with 340bId or pharmacyId filter. The view handles all complex SQL logic including monthly aggregation.
        Lambda formats the response as a stacked area chart with categories and series.
    """
    tile_name = "account-detail-anomalous-transactions-volume"
    session = None
    valid_filter_column_map = {
        "brands": "Anomaly_Brand" # as this tile represent data at an account level only brand filter is applicable and supported in the view
    }
    filter_string = ""
    time_period = 'quarterly'  # Default time period for filtering if not provided in query parameters
    
    try:
        # STEP 1: Validate that exactly one of 340bId or pharmacyId is provided (REQUIRED)
        is_valid, error_response, id_type, id_value = validate_account_id_parameters(query_params, tile_name)
        if not is_valid:
            return error_response
        
        # STEP 2: Validate optional date parameters (from, to) and build filters
        if query_params:
            is_valid, error_response = validate_query_parameters(query_params, tile_name)
            if not is_valid:
                return error_response
            filter_string = generate_global_filters_from_query_params(query_params, valid_filter_column_map)
        
        session = get_session()
        
        # Query the view with appropriate ID filter based on id_type
        raw_query = AccountDetailsCharts.ANOMALIES_BY_CE.value if id_type == "340B" else AccountDetailsCharts.ANOMALIES_BY_CP.value
            
        query = text(raw_query.format(query_params=filter_string))
        time_period = query_params.get('time-period', 'quarterly') if query_params else 'quarterly'
        query_placeholder_values = {
            "account_id": id_value,
            "time_period": time_period,
            "max_date": get_date_for_time_period(time_period)
        }

        result = session.execute(query, query_placeholder_values).fetchall()
        
        # STEP 4: Handle no data scenario with empty categories and zero-filled series
        if not result:
            return {
                "categories": [],
                "series": [{"name": "Transaction Volume", "data": [], "type": "area", "yAxis": 0}]
            }
        
        categories = [row.TimePeriod for row in result]
        anomaly_count = [int(row.value or 0) for row in result]
        
        return {
            "categories": categories,
            "series": [{"name": "Transaction Volume", "data": anomaly_count, "type": "area", "yAxis": 0}]
        }
        
    except ValueError as e:
        logger.error(f"Validation error in {tile_name}: {e}")
        return create_error_response(INVALID_PARAMS, str(e), tile_name)
    except Exception as e:
        logger.error(f"Unexpected error fetching {tile_name} data: {e}")
        return _classify_database_error(e, tile_name, "vwAnomalousTransactions",is_view=True)
    finally:
        if session:
            session.close()


def get_account_detail_covered_entity_purchase_trends_data(query_params: dict = None):
    """
    Fetch purchase quantity trends over time for a specific account for the account-detail-covered-entity-purchase-trends tile.
    
    Database Table: 340B_ProcessedData
    
    This tile returns monthly purchase quantity data for a specific account in a line chart format.
    Either 340bId OR pharmacyId parameter is REQUIRED for this tile (exactly one must be provided).
    
    Args:
        query_params: Dictionary of query parameters
            - 340bId (required*): The 340B covered entity ID to retrieve
            - pharmacyId (required*): The pharmacy ID to retrieve
            - brands: Comma-separated list of brands to filter by (optional)
            - time-period: Time period for filtering - "monthly", "quarterly", "half-yearly", "yearly" (optional, default: "quarterly")
            
            *Note: Exactly one of 340bId or pharmacyId must be provided
    
    Returns:
        Dictionary containing:
            - categories: List of month abbreviations (Jan, Feb, Mar, etc.)
            - series: List with exactly 1 series for line chart:
                     "Purchase Quantity" (yAxis: 0)
        On error, returns error object with "error", "message", and "tileName" fields.
    
    Implementation:
        Queries 340B_ProcessedData table directly using simple SELECT statement
        with ID filter (either 340bId or pharmacyId). The table handles all complex SQL logic including 
        monthly aggregation.
        Lambda formats the response as a line chart with categories and series.
    
    Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 7.4, 8.1, 8.2, 10.1, 10.2, 10.3
    """
    tile_name = "account-detail-covered-entity-purchase-trends"
    session = None
    valid_filter_column_map = {
        "brands": "Brand" # Displays data for a specific account, so only brand filter is applicable and supported in the view
    }
    filter_string = ""
    time_period = 'quarterly'  # Default time period for filtering if not provided in query parameters
    
    try:
        # STEP 1: Validate account ID parameters (340bId OR pharmacyId - exactly one required)
        is_valid, error_response, id_type, id_value = validate_account_id_parameters(query_params, tile_name)
        if not is_valid:
            return error_response
        
        # STEP 2: Validate optional date parameters (from, to)
        if query_params:
            is_valid, error_response = validate_query_parameters(query_params, tile_name)
            if not is_valid:
                return error_response
            
            time_period = query_params.get('time-period', 'quarterly')
            
            # STEP 2a: Build filter string for optional filters (brands, state)
            filter_string = generate_global_filters_from_query_params(query_params, valid_filter_column_map)
        
        
        session = get_session()
        
        # Query the view with appropriate ID column based on id_type
        if id_type == "340B":
            raw_query = AccountDetailsCharts.PUR_BY_CE.value
        else:  # Pharmacy
            raw_query = AccountDetailsCharts.PUR_BY_CP.value

        query = text(raw_query.format(query_params=filter_string))
        query_placeholder_values = {
            "account_id": id_value,
            "time_period": time_period,
            "max_date": get_date_for_time_period(time_period)
        }
        
        result = session.execute(query, query_placeholder_values).fetchall()
        
        # STEP 4: Handle no data scenario with empty categories and zero-filled series
        if not result:
            return {
                "categories": [],
                "series": [
                    {
                        "name": PURCHASE_QUANTITY,
                        "data": [],
                        "type": "line",
                        "yAxis": 0
                    }
                ]
            }
        
        
        categories = []
        purchase_quantities = []
        for row in result:
            categories.append(row.TimePeriod)
            
            # Add purchase quantity (convert to int to handle Decimal types from database)
            purchase_quantities.append(int(row.value or 0))
        
        # Format as line chart data
        chart_data = {
            "categories": categories,
            "series": [
                {
                    "name": PURCHASE_QUANTITY,
                    "data": purchase_quantities,
                    "type": "line",
                    "yAxis": 0
                }
            ]
        }
        
        return chart_data
        
    except ValueError as e:
        # Handle validation errors
        logger.error(f"Validation error in {tile_name}: {e}")
        return {
            "error": INVALID_PARAMS,
            "message": str(e),
            "tileName": tile_name
        }
    except Exception as e:
        # Handle unexpected errors
        logger.error(f"Unexpected error fetching {tile_name} data: {e}")
        return _classify_database_error(e, tile_name, "340B_ProcessedData")
    finally:
        # Always close the session
        if session:
            session.close()


def get_account_detail_covered_entity_dispense_trends_data(query_params: dict = None):
    """
    Fetch dispense quantity trends over time for a specific account for the account-detail-covered-entity-dispense-trends tile.
    
    Database View: vwAccountDetailCoveredEntityDispenseTrends
    
    This tile returns monthly dispense quantity data for a specific account in a line chart format.
    Either 340bId OR pharmacyId parameter is REQUIRED for this tile (exactly one must be provided).
    
    Args:
        query_params: Dictionary of query parameters
            - 340bId (required*): The 340B covered entity ID to retrieve
            - pharmacyId (required*): The pharmacy ID to retrieve
            - brands: Comma-separated list of brands to filter by (optional)
            - time-period: Time period for filtering - "monthly", "quarterly", "half
            
            *Exactly one of 340bId or pharmacyId must be provided
    
    Returns:
        Dictionary containing:
            - categories: List of month abbreviations (Jan, Feb, Mar, etc.)
            - series: List with exactly 1 series for line chart:
                     "Dispense Quantity" (yAxis: 0)
        On error, returns error object with "error", "message", and "tileName" fields.
    
    Implementation:
        Queries 340B_340BDispenses and 340B_Non340BDispenses tables directly using simple SELECT statement
        with ID filter (either 340bId or pharmacyId). The tables handle all complex SQL logic including 
        monthly aggregation and UNION logic for both account types.
        Lambda formats the response as a line chart with categories and series.
    
    Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 7.4, 8.1, 8.2, 10.1, 10.2, 10.3
    """
    tile_name = "account-detail-covered-entity-dispense-trends"
    session = None
    valid_filter_column_map = {
        "brands": "Brand" # Displays data for a specific account, so only brand filter is applicable and supported in the view
    }
    filter_string = ""
    time_period = 'quarterly'  # Default time period for filtering if not provided in query parameters
    
    try:
        # STEP 1: Validate account ID parameters (exactly one of 340bId or pharmacyId required)
        is_valid, error_response, id_type, id_value = validate_account_id_parameters(query_params, tile_name)
        if not is_valid:
            return error_response
        
        # STEP 2: Validate optional date parameters (from, to)
        if query_params:
            is_valid, error_response = validate_query_parameters(query_params, tile_name)
            if not is_valid:
                return error_response
            
            time_period = query_params.get('time-period', 'quarterly')

            filter_string = generate_global_filters_from_query_params(query_params, valid_filter_column_map)
        
        
        session = get_session()
        
        # Determine which ID column to filter by based on id_type
        if id_type == "340B":
            template = AccountDetailsCharts.DISP_BY_CE.value
        else:  # id_type == "Pharmacy"
            template = AccountDetailsCharts.DISP_BY_CP.value

        query_placeholder_values = {
            "account_id": id_value,
            "time_period": time_period,
            "max_date": get_date_for_time_period(time_period)
        }
        query = text(template.format(query_params=filter_string))
        result = session.execute(query, query_placeholder_values).fetchall()
        
        # STEP 4: Handle no data scenario with empty categories and zero-filled series
        if not result:
            return {
                "categories": [],
                "series": [
                    {
                        "name": DISPENSE_QUANTITY,
                        "data": [],
                        "type": "line",
                        "yAxis": 0
                    }
                ]
            }
        
        # STEP 5: Format response as line chart with categories and series
        categories = []
        dispense_quantities = []
        
        for row in result:
            # Use month abbreviation from view (Jan, Feb, Mar, etc.)
            categories.append(row.TimePeriod)
            
            # Add dispense quantity (convert to int to handle Decimal types from database)
            dispense_quantities.append(int(row.value or 0))
        
        # Format as line chart data
        chart_data = {
            "categories": categories,
            "series": [
                {
                    "name": DISPENSE_QUANTITY,
                    "data": dispense_quantities,
                    "type": "line",
                    "yAxis": 0
                }
            ]
        }
        
        return chart_data
        
    except ValueError as e:
        # Handle validation errors
        logger.error(f"Validation error in {tile_name}: {e}")
        return create_error_response(INVALID_PARAMS, str(e), tile_name)
    except Exception as e:
        # Handle unexpected errors
        logger.error(f"Unexpected error fetching {tile_name} data: {e}")
        return _classify_database_error(e, tile_name, "340B_340BDispenses / 340B_Non340BDispenses")
    finally:
        # Always close the session
        if session:
            session.close()


def get_account_detail_anomalies_data(query_params: dict = None):
    """
    Fetch list of anomalies for a specific account for the account-detail-anomalies tile.
    
    Database View: vwAccountDetailAnomalies
    
    This tile returns a list of anomalies for a specific account with all required fields
    including anomalyId, linkageScore, brand, date, daysOpen, region, chargeback, wac, and action.
    Either 340bId OR pharmacyId parameter is REQUIRED for this tile (exactly one must be provided).
    
    Args:
        query_params: Dictionary of query parameters
            - 340bId (required*): The 340B covered entity ID to retrieve
            - pharmacyId (required*): The pharmacy ID to retrieve
            - from (optional): Start date for filtering (format: YYYY-MM-DD)
            - to (optional): End date for filtering (format: YYYY-MM-DD)
            - limit (optional): Maximum number of results (positive integer)
            
            *Note: Exactly one of 340bId or pharmacyId must be provided, not both
    
    Returns:
        Array of anomaly objects containing:
            - anomalyId: 8-character unique identifier (string)
            - linkageScore: Confidence score 0-100 (integer)
            - brand: Brand name (string)
            - date: Anomaly date in MM/DD/YYYY format (string)
            - daysOpen: Days since creation formatted as "X Day" or "X Days" (string)
            - region: Geographic region (string)
            - chargeback: Formatted chargeback amount with K/M suffix (string)
            - wac: Formatted WAC amount with K/M suffix (string)
            - action: Current status/action (string)
        On error, returns error object with "error", "message", and "tileName" fields.
    
    Implementation:
        Queries vwAccountDetailAnomalies view directly using simple SELECT statement
        with either 340bId or pharmacyId filter. The view handles all complex SQL logic 
        including date formatting, days open calculation, and JOINs with HRSA table for 
        region data. Lambda formats monetary values using format_monetary_value() helper.
    
    Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 7.4, 8.1, 8.2, 10.1, 10.2, 10.3, 10.5
    """
    tile_name = "account-detail-anomalies"
    session = None
    
    try:
        # STEP 1: Validate account ID parameters (REQUIRED - exactly one of 340bId or pharmacyId)
        is_valid, error_response, id_type, id_value = validate_account_id_parameters(query_params, tile_name)
        if not is_valid:
            return error_response
        
        # STEP 2: Validate optional date parameters (from, to) and limit parameter
        if query_params:
            is_valid, error_response = validate_query_parameters(query_params, tile_name)
            if not is_valid:
                return error_response
        
        # STEP 3: Query database view with appropriate ID filter based on id_type
        session = get_session()
        
        # Query the view with appropriate ID column based on id_type
        if id_type == "340B":
            query = text("""
                SELECT
                    anomalyId, accountId, pharmacyId, anomalyEntityName,
                    linkageScore, brand, date, daysOpen, region,
                    chargeback, wac, units, dollars, state, city, action
                FROM vwAccountDetailAnomalies
                WHERE `accountId` = :id_value
            """)
        else:  # id_type == "Pharmacy"
            query = text("""
                SELECT
                    anomalyId, accountId, pharmacyId, anomalyEntityName,
                    linkageScore, brand, date, daysOpen, region,
                    chargeback, wac, units, dollars, state, city, action
                FROM vwPharmacyDetailAnomalies
                WHERE pharmacyId = :id_value
            """)
        
        result = session.execute(query, {"id_value": id_value}).fetchall()
        
        # STEP 4: Handle no data scenario by returning empty array
        if not result:
            return []
        
        # STEP 5: Format monetary values and return array of anomaly objects
        anomalies = []
        for row in result:
            anomaly = {
                "anomalyId": row.anomalyId or "",
                "accountId": row.accountId or "",
                "pharmacyId": row.pharmacyId or "",                
                "anomalyEntityName": row.anomalyEntityName,
                "linkageScore": int(row.linkageScore or 0),
                "brand": row.brand or "",
                "anomalyDate": row.date or "",
                "daysOpen": row.daysOpen or "0 Days",
                "region": row.region or "",
                # Format monetary values using helper function
                "chargeback": format_monetary_value(row.chargeback),
                "wac": format_monetary_value(row.wac),
                "units": row.units,
                "dollars": row.dollars,
                "state": row.state,
                "city": row.city,
                "action": row.action or ""
            }
            anomalies.append(anomaly)
        
        return anomalies
        
    except ValueError as e:
        # Handle validation errors
        logger.error(f"Validation error in {tile_name}: {e}")
        return {
            "error": INVALID_PARAMS,
            "message": str(e),
            "tileName": tile_name
        }
    except Exception as e:
        # Handle unexpected errors
        logger.error(f"Unexpected error fetching {tile_name} data: {e}")
        
        # Check for specific error types
        error_message = str(e).lower()
        if ERROR_DOES_NOT_EXIST in error_message or ERROR_UNKNOWN_TABLE in error_message:
            return {
                "error": VIEW_NOT_FOUND,
                "message": "Database view vwAccountDetailAnomalies does not exist",
                "tileName": tile_name
            }
        elif "connection" in error_message or "connect" in error_message:
            return {
                "error": CONNECTION_FAILED,
                "message": ERROR_CONNECTION,
                "tileName": tile_name
            }
        else:
            return {
                "error": INTERNAL_SERVER_ERROR,
                "message": f"An unexpected error occurred: {str(e)}",
                "tileName": tile_name
            }
    finally:
        # Always close the session
        if session:
            session.close()


# ============================================================================
# Dispatch table mapping tile names to their data-fetch functions.
# Add new database-connected tiles here — no branching logic required.
# ============================================================================
_TILE_HANDLERS = {
    # Overview Page
    "summary-kpis":                                    get_summary_kpis_data,
    "anomaly-kpis":                                    get_anomaly_kpis_data,
    "340b-growth-by-drivers":                          get_340b_growth_by_drivers_data,
    "340b-covered-entity-volume":                      get_340b_covered_entity_volume_data,
    "dispense-vs-purchase-volume":                     get_dispense_vs_purchase_volume_data,
    "cecp-split":                                      get_cecp_split_data,
    "340b-sales-discount":                             get_340b_sales_discount_data,
    "340b-wac-cecp":                                   get_340b_wac_cecp,
    "340b-chbk-cecp":                                  get_340b_chbk_cecp,
    "chbk-per-day":                                    get_chbk_per_day_data,
    "top-340b-accounts-by-avg-hcp-purchase":           get_top_340b_accounts_by_avg_hcp_purchase_data,
    # All Anomalies Page
    "anomalies-list":                                  get_anomalies_list_data,
    "anomaly-detail-kpis":                             get_anomaly_detail_kpis_data,
    "anomalous-transactions":                          get_anomalous_transactions_data,
    "anomalies-confidence-accounts":                   get_anomalies_confidence_accounts_data,
    "anomalies-confidence-growth":                     get_anomalies_confidence_growth_data,
    "anomalies-score-growth":                          get_anomalies_score_growth_data,
    "anomalous-transaction-map-chargeback":            get_anomalous_transaction_map_chargeback_data,
    "anomalous-transaction-map-priority":              get_anomalous_transaction_map_priority_data,
    # Accounts Page
    "accounts-summary-kpis":                           get_accounts_summary_kpis_data,
    "top-340b-accounts":                               get_top_340b_accounts_data,
    "contract-pharmacy-accounts":                      get_contract_pharmacy_accounts_data,
    "quarterly-dispense-purchase-comparison-by-corp":  get_quarterly_dispense_purchase_comparison_by_corp_data,
    "quarterly-dispense-purchase-comparison-by-state": get_quarterly_dispense_purchase_comparison_by_state_data,
    # Account Details Page
    "account-detail-header":                           get_account_detail_header_data,
    "account-detail-kpis":                             get_account_detail_kpis_data,
    "account-detail-anomalous-transactions-volume":    get_account_detail_anomalous_transactions_volume_data,
    "account-detail-covered-entity-purchase-trends":   get_account_detail_covered_entity_purchase_trends_data,
    "account-detail-covered-entity-dispense-trends":   get_account_detail_covered_entity_dispense_trends_data,
    "account-detail-anomalies":                        get_account_detail_anomalies_data,
}


def get_tile_data(tile_name: str, query_params: dict = None):
    """
    Fetch data for a single tile from database or static data.

    Database tiles query views directly and return standardized error responses on failure.
    Static fallback (TILE_DATA) is only used for tiles without database implementations.

    Args:
        tile_name: The name of the tile to fetch (e.g., 'summary-kpis')
        query_params: Optional dictionary of query parameters for filtering/customization

    Returns:
        Dictionary containing tile data, or None if tile doesn't exist

    Validates: Requirements 1.3, 3.4
    """
    handler = _TILE_HANDLERS.get(tile_name)
    if handler:
        return handler(query_params)
    return TILE_DATA.get(tile_name)


# ============================================================================
# API Route Handlers
# ============================================================================

# Bundle: return all four tiles at once
@app.get("/api/v1/tiles")
@tracer.capture_method
def get_tiles_bundle():
    """
    Fetch one or more tiles based on query string parameter 'tilename'
    Supports: /api/v1/tiles?tilename=anomalous-transactions
    Or: /api/v1/tiles?tilename=anomalous-transactions,anomalies-confidence-accounts
    Additional parameters can be passed for filtering (e.g., limit, from, to, accountId, segment)
    
    Returns:
        Dictionary with tile names as keys and tile data as values.
        For unknown tiles, returns error object with "error", "message", and "tileName" fields.
        For missing tilename parameter, returns error object with "error" and "message" fields.
        For invalid tile names, returns error object with validation message.
    """
    print(f"** inside /api/v1/tiles {app.current_event.query_string_parameters}")
    
    try:
        # Get query string parameters
        query_params = app.current_event.query_string_parameters or {}
        tilename_param = query_params.get('tilename', '')
        
        # If no tilename specified, return error with consistent format
        if not tilename_param:
            return create_error_response(
                MISSING_REQUIRED_PARAMETER,
                "Please specify one or more tile names using ?tilename=tile1,tile2"
            )
        
        # Parse comma-separated tile names
        requested_tiles = [name.strip() for name in tilename_param.split(',')]
        
        # Validate tile names for kebab-case convention
        for tile_name in requested_tiles:
            is_valid, error_msg = validate_tile_name(tile_name)
            if not is_valid:
                return create_error_response(
                    "Invalid tile name",
                    f"Tile '{tile_name}': {error_msg}",
                    tile_name
                )
        
        # Extract additional parameters (excluding tilename)
        additional_params = {
            key: value 
            for key, value in query_params.items() 
            if key != 'tilename' and value
        }
        
        # Build response dictionary containing only the requested tiles
        response = {}
        dual_series_tiles = ["anomalous-transactions", "340b-covered-entity-volume", "dispense-vs-purchase-volume"]
        
        for tile_name in requested_tiles:
            tile_data = get_tile_data(tile_name, additional_params)
            if tile_data is not None:
                # Additional validation for dual-series tiles in batch requests
                if tile_name in dual_series_tiles:
                    # Check if tile_data is an error response
                    if isinstance(tile_data, dict) and 'error' in tile_data:
                        response[tile_name] = tile_data
                    else:
                        # Validate dual-series structure for batch compatibility
                        is_valid, error_response = validate_dual_series_batch_compatibility(tile_data, tile_name, requested_tiles)
                        if not is_valid:
                            response[tile_name] = error_response
                        else:
                            response[tile_name] = tile_data
                else:
                    response[tile_name] = tile_data
            else:
                # Return consistent error format for unknown tiles
                response[tile_name] = create_error_response(
                    "Unknown tile",
                    f"Tile '{tile_name}' is not recognized. Please check the tile name and try again.",
                    tile_name
                )
        
        return response
        
    except Exception as e:
        logger.error(f"Error in get_tiles_bundle: {e}")
        return create_error_response(
            INTERNAL_SERVER_ERROR,
            str(e)
        )