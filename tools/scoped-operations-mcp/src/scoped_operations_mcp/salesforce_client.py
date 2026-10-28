from __future__ import annotations

# AgentChat/coding_agent 2026-08-03T23:30:00Z
# AgentChat/coding_agent 2026-07-26T00:51:47Z
# AgentChat/coding_agent 2026-08-06T11:45:00Z
# AgentChat/coding_agent 2026-08-06T16:20:00Z
# AgentChat/coding_agent 2026-08-07T12:42:00Z

import base64
import binascii
import hashlib
import json
import os
import re
import threading
import time
from calendar import monthrange
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from email import policy as email_policy
from email.parser import HeaderParser
from email.utils import getaddresses, parseaddr
from html import unescape
from pathlib import Path
from typing import Any, Collection, Iterator, Mapping, Sequence
from urllib.parse import urlsplit
from xml.etree import ElementTree
from xml.sax.saxutils import escape as escape_xml

import requests
from dotenv import dotenv_values

from .internal_communications import (
    internal_request_day,
    restore_verified_internal_request_day,
)

try:  # Linux production lock; Windows tests retain process-local serialization.
    import fcntl
except ImportError:  # pragma: no cover - exercised by production Linux.
    fcntl = None  # type: ignore[assignment]


SALESFORCE_ID = re.compile(r"^[A-Za-z0-9]{15}(?:[A-Za-z0-9]{3})?$")
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
EMAIL_IN_TEXT = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,239}$")
# The derived ``support-email:<id>`` is also the durable journal target, whose
# fixed contract is 200 characters.
SUPPORT_EMAIL_SOURCE_ID = re.compile(r"^[A-Za-z0-9._:@+-]{1,186}$")
SUPPORT_EMAIL_SOURCE_MARKER = re.compile(r"(?i)\bsource[ \t]+key[ \t]*:")
SUPPORT_EMAIL_EXCLUDED_ACCOUNT_PARTS = ("demo", "test", "template", "fallback")
NOVA_ID = re.compile(r"^A-[0-9]{1,20}$", re.IGNORECASE)
LOCATION_STATUS_VALUES = {
    "active": "Active",
    "inactive": "Inactive",
    "storage": "Storage",
}
SALESFORCE_OPERATION_LOCK = threading.RLock()

# This is a server-owned business workflow, not a caller-selected template
# surface. DeveloperName is stable across Salesforce org copies while the
# record ID is org-specific. Keeping the mapping private prevents an agent from
# turning the guarded send into arbitrary template discovery or delivery.
REFUND_SUBMITTED_TEMPLATE_DEVELOPER_NAME = "A_Refund_was_Submitted"
REFUND_SUBMITTED_TEMPLATE_SUBJECT = "Your Nova refund has been submitted"
CREDIT_APPLIED_TEMPLATE_DEVELOPER_NAME = "Credit_was_applied_to_your_account"
CREDIT_APPLIED_TEMPLATE_SUBJECT = "Your Nova account credit has been approved"
SUPPORT_ONE_OFF_TEMPLATE_DEVELOPER_NAME = "NovaPOS_Support_One_Off_Message"
SUPPORT_ONE_OFF_TEMPLATE_NAME = "NovaPOS Support One-Off Message"
SUPPORT_ONE_OFF_TEMPLATE_SUBJECT = "Nova POS Support Update"
SUPPORT_ORG_WIDE_EMAIL_ADDRESS = "support@novapointofsale.com"
BILLING_ORG_WIDE_EMAIL_ADDRESS = "billing@novapointofsale.com"
DARIUS_ORG_WIDE_EMAIL_ADDRESS = "darius@novapointofsale.com"
DEPARTMENT_ORG_WIDE_EMAIL_ADDRESSES = {
    "support": SUPPORT_ORG_WIDE_EMAIL_ADDRESS,
    "billing": BILLING_ORG_WIDE_EMAIL_ADDRESS,
}
APPROVED_EMAIL_TEMPLATE_FOLDERS = {
    "00lA0000001VKQq": "Customer Service/Billing",
    "00lA0000000peVU": "Support Templates",
}
EMAIL_TEMPLATE_CLASS_APPROVED = "approved_sendable"
EMAIL_TEMPLATE_CLASS_PENDING = "active_pending_review"
EMAIL_TEMPLATE_CLASS_CONTENT_PENDING = "content_pending"
EMAIL_TEMPLATE_CLASS_REJECTED = "rejected_obsolete_internal_only"
EMAIL_TEMPLATE_CLASS_BROKEN = "broken_or_unsafe"
EMAIL_TEMPLATE_CLASS_MISSING = "missing"
EMAIL_TEMPLATE_SENDER_POLICY = "department_org_wide"
DIRECT_DARIUS_REPLY_SENDER_POLICY = "verified_direct_darius_reply_org_wide"
CURATED_REJECTED_TEMPLATE_MARKERS = frozenset({"internal", "obsolete", "deprecated"})
CREDENTIALS_TICKET_ID = "a0GRc00000JLExtMAH"
CREDENTIALS_TICKET_NUMBER = "347370"
CREDENTIALS_TEMPLATE_ID = "00XA0000001Wt30MAC"
CREDENTIALS_TEMPLATE_DEVELOPER_NAME = "Customers_Automated_Company_Username_Password"
CREDENTIALS_TEMPLATE_NAME = "Customers - Automated Company Username  / Password"
CREDENTIALS_TEMPLATE_SUBJECT = "Please read email to retrieve your NovaPOS Username / Password"
CREDENTIALS_AUTHORIZED_RECIPIENTS = (
    "avi55katz@hotmail.com",
    "cam.a.courtney@gmail.com",
)
CREDENTIALS_EXCLUDED_RECIPIENTS = frozenset(
    {
        "realtor@oksanapiven.com",
        "oksanapiven@yahoo.com",
    }
)
CREDENTIALS_RECIPIENT_EVIDENCE_FIELDS = (
    "Email_Address_to_Send_Ticket__c",
    "Notes_Send_To_Client__c",
    "Description__c",
)

# The registry identity is the exact approved folder plus DeveloperName. A
# display name alone is never sufficient because duplicate and employee-named
# variants exist in the live folders. Unknown live templates are inventory-only
# and remain non-sendable.
EMAIL_TEMPLATE_REGISTRY: dict[tuple[str, str], dict[str, Any]] = {
    ("00lA0000001VKQq", "NovaPOS_Billing_Inquiry_Update"): {
        "situation": "billing_inquiry_update",
        "folderId": "00lA0000001VKQq",
        "name": "NovaPOS Billing Inquiry Update",
        "developerName": "NovaPOS_Billing_Inquiry_Update",
        "subject": "NovaPOS Billing Inquiry Update",
        "classification": EMAIL_TEMPLATE_CLASS_APPROVED,
        "department": "billing",
        "detailFields": ("last4Digits", "message"),
        "recipientPolicy": "ticket_contact",
        "senderPolicy": EMAIL_TEMPLATE_SENDER_POLICY,
        "sensitivity": "standard",
        "previewTool": "salesforce_ticket_template_email_preview",
        "sendTool": "salesforce_ticket_template_email_send",
        "owningLanes": ("direct_codex", "billing_agent"),
    },
    ("00lA0000000peVU", "NovaPOS_API_Intro"): {
        "situation": "api_intro",
        "folderId": "00lA0000000peVU",
        "name": "NovaPOS API Intro",
        "developerName": "NovaPOS_API_Intro",
        "subject": "NovaPOS API access information",
        "expectedTemplateId": "00XRc000007pDs1MAE",
        "classification": EMAIL_TEMPLATE_CLASS_APPROVED,
        "department": "billing",
        "detailFields": (),
        "requiredBodyFragments": (
            "14-day trial period",
            "one-time setup fee of $100",
            "monthly usage fee of $50",
        ),
        "recipientPolicy": "account_primary_only",
        "senderPolicy": EMAIL_TEMPLATE_SENDER_POLICY,
        "sensitivity": "standard",
        "previewTool": "salesforce_ticket_template_email_preview",
        "sendTool": "salesforce_ticket_template_email_send",
        "owningLanes": ("direct_codex", "billing_agent"),
    },
    ("00lA0000001VKQq", "Account_Close_Request"): {
        "situation": "account_close_request",
        "folderId": "00lA0000001VKQq",
        "name": "Account Close Request",
        "developerName": "Account_Close_Request",
        "subject": "Account Close Request",
        "classification": EMAIL_TEMPLATE_CLASS_APPROVED,
        "department": "billing",
        "detailFields": (),
        "recipientPolicy": "account_primary_and_ticket_listed",
        "senderPolicy": EMAIL_TEMPLATE_SENDER_POLICY,
        "sensitivity": "standard",
        "previewTool": "salesforce_ticket_template_email_preview",
        "sendTool": "salesforce_ticket_template_email_send",
        "owningLanes": ("direct_codex", "billing_agent"),
    },
    ("00lA0000001VKQq", "NovaPOS_Account_Cancellation_Confirmed"): {
        "situation": "account_cancellation_confirmed",
        "folderId": "00lA0000001VKQq",
        "name": "NovaPOS Account Cancellation Confirmed",
        "developerName": "NovaPOS_Account_Cancellation_Confirmed",
        "subject": "Your NOVA POS account has been closed",
        "classification": EMAIL_TEMPLATE_CLASS_APPROVED,
        "department": "billing",
        "detailFields": (),
        "recipientPolicy": "account_primary_and_ticket_listed",
        "senderPolicy": EMAIL_TEMPLATE_SENDER_POLICY,
        "sensitivity": "standard",
        "previewTool": None,
        "sendTool": "salesforce_account_cancellation_confirmation_email_send",
        "owningLanes": ("billing_agent",),
        "specialized": True,
    },
    ("00lA0000001VKQq", CREDIT_APPLIED_TEMPLATE_DEVELOPER_NAME): {
        "situation": "credit_applied",
        "folderId": "00lA0000001VKQq",
        "name": "Credit was applied to your account",
        "developerName": CREDIT_APPLIED_TEMPLATE_DEVELOPER_NAME,
        "subject": CREDIT_APPLIED_TEMPLATE_SUBJECT,
        "classification": EMAIL_TEMPLATE_CLASS_APPROVED,
        "department": "billing",
        "detailFields": ("credit_amount_cents",),
        "recipientPolicy": "account_primary_and_ticket_listed",
        "senderPolicy": EMAIL_TEMPLATE_SENDER_POLICY,
        "sensitivity": "standard",
        "previewTool": None,
        "sendTool": "salesforce_ticket_credit_confirmation_email_send",
        "owningLanes": ("billing_agent",),
        "specialized": True,
    },
    ("00lA0000001VKQq", REFUND_SUBMITTED_TEMPLATE_DEVELOPER_NAME): {
        "situation": "refund_submitted",
        "folderId": "00lA0000001VKQq",
        "name": "A Refund was Submitted",
        "developerName": REFUND_SUBMITTED_TEMPLATE_DEVELOPER_NAME,
        "subject": REFUND_SUBMITTED_TEMPLATE_SUBJECT,
        "classification": EMAIL_TEMPLATE_CLASS_APPROVED,
        "department": "billing",
        "detailFields": ("refund_amount_cents",),
        "recipientPolicy": "account_primary_and_ticket_listed",
        "senderPolicy": EMAIL_TEMPLATE_SENDER_POLICY,
        "sensitivity": "standard",
        "previewTool": None,
        "sendTool": "salesforce_ticket_refund_confirmation_email_send",
        "owningLanes": ("billing_agent",),
        "specialized": True,
    },
    ("00lA0000001VKQq", CREDENTIALS_TEMPLATE_DEVELOPER_NAME): {
        "situation": "company_credentials_347370",
        "folderId": "00lA0000001VKQq",
        "name": CREDENTIALS_TEMPLATE_NAME,
        "developerName": CREDENTIALS_TEMPLATE_DEVELOPER_NAME,
        "subject": CREDENTIALS_TEMPLATE_SUBJECT,
        "expectedTemplateId": CREDENTIALS_TEMPLATE_ID,
        "classification": EMAIL_TEMPLATE_CLASS_APPROVED,
        "department": "support",
        "detailFields": ("requested_recipients",),
        "recipientPolicy": "ticket_347370_exact_authorized_recipients",
        "senderPolicy": EMAIL_TEMPLATE_SENDER_POLICY,
        "sensitivity": "credential_secret",
        "previewTool": "salesforce_ticket_company_credentials_email_preview",
        "sendTool": "salesforce_ticket_company_credentials_email_send",
        "owningLanes": ("direct_codex", "tickets_agent"),
        "specialized": True,
    },
    ("00lA0000000peVU", SUPPORT_ONE_OFF_TEMPLATE_DEVELOPER_NAME): {
        "situation": "support_one_off_message",
        "folderId": "00lA0000000peVU",
        "name": SUPPORT_ONE_OFF_TEMPLATE_NAME,
        "developerName": SUPPORT_ONE_OFF_TEMPLATE_DEVELOPER_NAME,
        "subject": SUPPORT_ONE_OFF_TEMPLATE_SUBJECT,
        "classification": EMAIL_TEMPLATE_CLASS_APPROVED,
        "department": "support",
        "detailFields": ("message",),
        "recipientPolicy": "ticket_contact",
        "senderPolicy": EMAIL_TEMPLATE_SENDER_POLICY,
        "sensitivity": "standard",
        "previewTool": "salesforce_ticket_template_email_preview",
        "sendTool": "salesforce_ticket_template_email_send",
        "owningLanes": ("direct_codex", "tickets_agent", "coding_agent"),
    },
}
APPROVED_TICKET_EMAIL_SITUATIONS: dict[str, dict[str, Any]] = {
    str(spec["situation"]): spec for spec in EMAIL_TEMPLATE_REGISTRY.values()
}


def _pending_email_workflow(
    situation: str,
    name: str,
    department: str,
    reason: str,
    *,
    classification: str = EMAIL_TEMPLATE_CLASS_PENDING,
    aliases: tuple[str, ...] = (),
    detail_fields: tuple[str, ...] = (),
    recipient_policy: str = "pending_operator_review",
) -> dict[str, Any]:
    return {
        "situation": situation,
        "name": name,
        "acceptedNames": (name, *aliases),
        "developerName": None,
        "folderId": (
            "00lA0000000peVU" if department == "support" else "00lA0000001VKQq"
        ),
        "classification": classification,
        "department": department,
        "detailFields": detail_fields,
        "recipientPolicy": recipient_policy,
        "senderPolicy": EMAIL_TEMPLATE_SENDER_POLICY,
        "sensitivity": "standard",
        "previewTool": None,
        "sendTool": None,
        "owningLanes": (
            ("direct_codex", "tickets_agent", "coding_agent")
            if department == "support"
            else ("direct_codex", "billing_agent")
        ),
        "rejectionReason": reason,
    }


def _curated_email_template_rejection_reason(record: dict[str, Any]) -> str | None:
    """Reject only explicit non-customer markers in bounded template metadata."""

    for field, label in (
        ("Name", "name"),
        ("DeveloperName", "developer name"),
        ("Subject", "subject"),
        ("Description", "description"),
    ):
        normalized = re.sub(
            r"[_\W]+",
            " ",
            str(record.get(field) or "").casefold(),
            flags=re.UNICODE,
        ).strip()
        tokens = set(normalized.split())
        marker = next(
            (
                candidate
                for candidate in sorted(CURATED_REJECTED_TEMPLATE_MARKERS)
                if candidate in tokens
            ),
            None,
        )
        if marker:
            return (
                f"explicit {marker} marker in template {label}; "
                "template is not customer-sendable"
            )
    return None


# Every operator-requested expansion remains discoverable even before it has an
# exact reviewed DeveloperName. These entries are intentionally not part of the
# sendable identity registry and therefore cannot be resolved for delivery.
CANONICAL_PENDING_EMAIL_WORKFLOWS: tuple[dict[str, Any], ...] = (
    _pending_email_workflow(
        "case_update",
        "Case Update",
        "support",
        "exact DeveloperName, fixed subject, rendered content, and recipient policy require review",
    ),
    _pending_email_workflow(
        "api_access_credentials",
        "NovaPOS API Access Credentials",
        "support",
        "exact template identity, sensitive-field behavior, and recipient policy require review",
    ),
    _pending_email_workflow(
        "api_capabilities_update_july_2026",
        "NovaPOS API Capabilities Update - July 2026",
        "support",
        "exact DeveloperName, fixed subject, and rendered content require review",
    ),
    _pending_email_workflow(
        "requested_documents_attached",
        "Requested Documents are attached",
        "support",
        "attachment contract, exact template identity, and recipient policy require review",
    ),
    _pending_email_workflow(
        "support_ticket_created",
        "Support Ticket Created",
        "support",
        "exact DeveloperName, fixed subject, and merge-field preview require review",
    ),
    _pending_email_workflow(
        "support_ticket_closed",
        "Support Ticket is Closed",
        "support",
        "exact DeveloperName, closure preconditions, and merge-field preview require review",
    ),
    _pending_email_workflow(
        "support_unable_to_reach_customer",
        "Unable to reach customer for support ticket",
        "support",
        "exact DeveloperName, fixed subject, and recipient policy require review",
    ),
    _pending_email_workflow(
        "support_unhappy_goodbye",
        "Unhappy - Is this really goodbye",
        "support",
        "multiple live variants exist; one department-neutral exact identity must be selected",
        classification=EMAIL_TEMPLATE_CLASS_BROKEN,
    ),
    _pending_email_workflow(
        "nova_wave_new_account_welcome",
        "New Account Welcome email",
        "support",
        "Nova Wave scope, exact DeveloperName, subject, and recipient policy require review",
    ),
    _pending_email_workflow(
        "api_write_capabilities",
        "NovaPOS API Now Supports Write Capabilities",
        "support",
        "exact DeveloperName, fixed subject, and current approved content require review",
    ),
    _pending_email_workflow(
        "software_billing_issue_notification",
        "Software Billing Issue Notification",
        "billing",
        "exact Jamie-owned template identity, fixed subject, and recipient policy require review",
    ),
    _pending_email_workflow(
        "accessing_billing_automation",
        "Accessing Billing Automation",
        "billing",
        "exact DeveloperName, fixed subject, and rendered content require review",
    ),
    _pending_email_workflow(
        "account_is_closed",
        "Account is closed",
        "billing",
        "must be distinguished from the existing cancellation-confirmed workflow",
    ),
    _pending_email_workflow(
        "account_in_decline",
        "Your account is in decline",
        "billing",
        "stored wording requires operator-approved replacement content",
        classification=EMAIL_TEMPLATE_CLASS_CONTENT_PENDING,
        aliases=("Your Credit Card Has Been Declined - NovaPOS",),
    ),
    _pending_email_workflow(
        "account_in_decline_spanish",
        "Your account is in decline - Spanish",
        "billing",
        "stored Spanish wording requires operator-approved replacement content",
        classification=EMAIL_TEMPLATE_CLASS_CONTENT_PENDING,
    ),
    _pending_email_workflow(
        "new_location_added",
        "A New Location Was Added to Your Account - NovaPOS",
        "billing",
        "the requested exact active template was not established in the approved-folder inventory",
        classification=EMAIL_TEMPLATE_CLASS_MISSING,
    ),
    _pending_email_workflow(
        "new_storage_location_added",
        "A New Storage Location Was Added to Your Account - NovaPOS",
        "billing",
        "live candidate exists but its storage-only scope versus new-location workflow is unresolved",
        classification=EMAIL_TEMPLATE_CLASS_BROKEN,
    ),
    _pending_email_workflow(
        "closing_or_deactivating_location_or_account",
        "Closing/Deactivating A Location or Account",
        "billing",
        "exact DeveloperName, lifecycle preconditions, and recipient policy require review",
    ),
    _pending_email_workflow(
        "payment_information_update_required",
        "Action Required: Please Update Your Payment Information",
        "billing",
        "exact DeveloperName, fixed subject, and decline-state preconditions require review",
    ),
    _pending_email_workflow(
        "future_credit_applied",
        "Future Credit was applied to your account - Nova POS",
        "billing",
        "stored wording requires operator-approved replacement content",
        classification=EMAIL_TEMPLATE_CLASS_CONTENT_PENDING,
    ),
    _pending_email_workflow(
        "refund_credit_approved_notification",
        "Nova Refund/Credit Approved Notification",
        "billing",
        "exact DeveloperName and distinction from existing refund/credit confirmations require review",
    ),
    _pending_email_workflow(
        "refund_policy_cancelled_locations",
        "Refund Policy for Cancelled Locations",
        "billing",
        "exact DeveloperName, fixed subject, and cancellation recipient policy require review",
    ),
    _pending_email_workflow(
        "decline_extension_approved",
        "Your Decline Extension Has Been Approved",
        "billing",
        "stored wording requires operator-approved replacement content",
        classification=EMAIL_TEMPLATE_CLASS_CONTENT_PENDING,
    ),
    _pending_email_workflow(
        "next_billing_date_notification",
        "NovaPOS Next Billing Date Notification",
        "billing",
        "no exact active template was present in the approved-folder inventory",
        classification=EMAIL_TEMPLATE_CLASS_MISSING,
    ),
    _pending_email_workflow(
        "generic_pending_reply",
        "Your Request is Currently Pending - NovaPOS",
        "billing",
        "generic reply body slot, exact identity, and recipient policy require review",
        aliases=("Your Request is Currently Pending – NovaPOS",),
    ),
    _pending_email_workflow(
        "billing_one_off_message",
        "NovaPOS Billing One-Off Message",
        "billing",
        "no exact approved stored template, fixed subject, body placeholder, or recipient policy exists",
        classification=EMAIL_TEMPLATE_CLASS_MISSING,
        detail_fields=("message",),
        recipient_policy="pending_exact_template_and_recipient_policy",
    ),
    {
        # This is a workflow label, not a guessed Salesforce EmailTemplate
        # identity. Empty acceptedNames prevents a similarly named live
        # template from being treated as reviewed.
        "situation": "direct_darius_inbound_reply",
        "name": "Direct Darius inbound reply (template pending)",
        "acceptedNames": (),
        "developerName": None,
        "folderId": "",
        "classification": EMAIL_TEMPLATE_CLASS_MISSING,
        "department": "direct_darius_reply",
        "detailFields": ("inbound_email_message_id",),
        "recipientPolicy": "exact_inbound_emailmessage_from_address",
        "senderPolicy": DIRECT_DARIUS_REPLY_SENDER_POLICY,
        "sensitivity": "standard",
        "previewTool": None,
        "sendTool": None,
        "owningLanes": ("direct_codex",),
        "rejectionReason": (
            "no exact approved stored reply template, fixed subject, rendered body, "
            "wrapper, or signature is registered; Darius reply delivery remains unavailable"
        ),
    },
)
BILLING_INQUIRY_ACCOUNT_PLACEHOLDER = "[Account Name]"
BILLING_INQUIRY_LAST4_PLACEHOLDER = "[Last 4 Digits]"
BILLING_INQUIRY_MESSAGE_PLACEHOLDER = (
    "[Billing inquiry update. Example: We were unable to find duplicate charges on the account "
    "for this card. Please submit any statement showing the duplicate charges for our review "
    "and further investigation.]"
)
SUPPORT_ONE_OFF_MESSAGE_PLACEHOLDER = (
    "[Support update. Example: We added the ability to print the refund policy. "
    "Install the linked update on each location computer.]"
)
TICKET_ATTACHMENT_EXTENSIONS = frozenset(
    {
        ".csv",
        ".docx",
        ".eml",
        ".gif",
        ".jpeg",
        ".jpg",
        ".json",
        ".md",
        ".pdf",
        ".png",
        ".pptx",
        ".tif",
        ".tiff",
        ".tsv",
        ".txt",
        ".webp",
        ".xlsx",
    }
)
TICKET_ATTACHMENT_ARCHIVE_EXTENSIONS = frozenset({".docx", ".pptx", ".xlsx"})
TICKET_ATTACHMENT_IMAGE_SIGNATURES = {
    ".gif": (b"GIF87a", b"GIF89a"),
    ".jpeg": (b"\xff\xd8\xff",),
    ".jpg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".tif": (b"II*\x00", b"MM\x00*"),
    ".tiff": (b"II*\x00", b"MM\x00*"),
}
MAX_TICKET_ATTACHMENT_BYTES = 10 * 1024 * 1024

# AgentChat/direct_codex 2026-07-24T13:45:00Z: add the fixed Friday
# Classic/Wave ticket aggregate used by the verified weekly Yaron workflow.

# AgentChat/direct_codex 2026-07-29T14:35:00Z: stage Salesforce deactivation guards before lifecycle changes.
LOOKUP_FIELDS = {
    "ticket": ("NovaPOS_Ticket__c", "Id,Name,Account__c,Contact__c,RecordTypeId,CreatedDate,LastModifiedDate"),
    "account": ("Account", "Id,Name,Company_Username__c,Nova_ID__c,Phone"),
    "contact": ("Contact", "Id,Name,AccountId,Email,Phone"),
    "location": (
        "NovaPOS_Location__c",
        "Id,Name,Account__c,Location_ID__c,Status__c,Bill_Amount__c,"
        "Chargify_Subscription_ID__c,NovaPOS_Billing_Schedule__c,"
        "Is_Location_on_GSPayTech_Gateway__c",
    ),
    "order": (
        "NovaPOS_Order__c",
        "Id,Name,Account__c,RecordTypeId,Contract_Name__c,Description__c,"
        "Existing_Order_Type__c,"
        "Reason_for_cancellation__c,Location_I_D__c,Chargify_Subscription_ID__c,"
        "Total_Number_of_Locations_for_this_order__c,Billing_Start_Date1__c,CreatedDate",
    ),
}
ACCOUNT_360_ACCOUNT_FIELDS = (
    "Id,Name,Company_Username__c,Nova_ID__c,Phone,Phone_II__c,Website,"
    "BillingStreet,BillingCity,BillingState,BillingPostalCode,BillingCountry,"
    "Status__c,Real_Account_Status__c,NovaPOS_Active__c,"
    "OwnerId,Owner.Name,Owner.Email,"
    "Nova_Account_Manager__c,Nova_Account_Manager__r.Name,Nova_Account_Manager__r.Email,"
    "PrimaryContact__c,PrimaryContact__r.Id,PrimaryContact__r.Name,"
    "PrimaryContact__r.FirstName,PrimaryContact__r.LastName,PrimaryContact__r.Email,"
    "PrimaryContact__r.Phone,PrimaryContact__r.MobilePhone,PrimaryContact__r.Title"
)
ACCOUNT_360_CONTACT_FIELDS = (
    "Id,Name,FirstName,LastName,AccountId,Email,Phone,MobilePhone,Title,"
    "MailingStreet,MailingCity,MailingState,MailingPostalCode,MailingCountry"
)
ACCOUNT_360_LOCATION_FIELDS = (
    "Id,Name,Account__c,Location_ID__c,Status__c,Bill_Amount__c,"
    "Chargify_Subscription_ID__c,NovaPOS_Billing_Schedule__c,"
    "Is_Location_on_GSPayTech_Gateway__c"
)
ACCOUNT_360_TICKET_FIELDS = (
    "Id,Name,RecordTypeId,RecordType.Name,Account__c,Contact__c,NovaPOS_Location__c,"
    "CreatedDate,LastModifiedDate,Is_Closed__c,Ticket_Closed_Date__c,"
    "Tech_Main_Issue__c,Technical_Issue__c,NOVA_Wave_Issue__c,"
    "NOVA_Wave_Technical_Issue__c,Customer_Contact__c"
)

TICKET_UPDATE_FIELDS = frozenset(
    {
        "Account__c",
        "Contact__c",
        "NovaPOS_Location__c",
        "Tech_Main_Issue__c",
        "Technical_Issue__c",
        "Customer_Contact__c",
        "Credit_Amount__c",
        "Refund_amount__c",
        "Is_Closed__c",
        "Ticket_Closed_Date__c",
        "Ticket_Closed_by_Rep__c",
        "Zoom_Engagement_ID__c",
        "Rescue_Session_ID__c",
    }
)
TICKET_UPDATE_FIELD_ALIASES: dict[str, str] = {}
TICKET_CLOSED_BY_REP_FIELD = "Ticket_Closed_by_Rep__c"
TICKET_CLOSED_BY_REP_FALLBACK = "Darius Parlor"
PAYMENT_CARD_TICKET_VALUE_FIELDS = (
    "Payment_Method__c",
    "Last_4_digits_on_Credit_Card__c",
    "Name_on_Card__c",
    "CC_Experation_Date__c",
    "CVV__c",
    "Street_Address_I__c",
    "Billing_Street_Address_II__c",
    "CIty__c",
    "State__c",
    "Country__c",
    "Billing_Zipcode__c",
)
PAYMENT_CARD_TICKET_TEXT_FIELDS = (
    "Description__c",
    "Billing_Notes_Internal__c",
    "Notes_Send_To_Client__c",
)
SUPPORT_QUALITY_TICKET_RECORD_TYPES = (
    "1. NOVA Classic",
    "2. Nova Wave",
)
OPERATIONAL_TICKET_RECORD_TYPES = (
    *SUPPORT_QUALITY_TICKET_RECORD_TYPES,
    "3. Billing",
)
SUPPORT_QUALITY_TICKET_ROW_CEILING = 2000
SUPPORT_QUALITY_TICKET_FIELDS = (
    "Id,RecordType.Name,CreatedDate,Is_Closed__c,Ticket_Closed_Date__c,"
    "Ticket_Created_by__c,Ticket_Closed_by_Rep__c,Owner.Name,CreatedBy.Name,"
    "Description__c,Tech_Main_Issue__c,Technical_Issue__c,"
    "NOVA_Wave_Issue__c,NOVA_Wave_Technical_Issue__c"
)

LOCATION_UPDATE_FIELDS = frozenset(
    {
        "Name",
        "Status__c",
        "Location_ID__c",
        "NovaPOS_Billing_Schedule__c",
        "Chargify_Subscription_ID__c",
    }
)

ORDER_CREATE_FIELDS = frozenset(
    {
        "Account__c",
        "RecordTypeId",
        "Contract_Name__c",
        "Description__c",
        "Sales_Additional_Notes__c",
        "Email_Address__c",
        "Billing_Address__c",
        "Is_This_a_Free_Nova_Order__c",
        "Contact__c",
        "Order_Assigned_To_c__c",
        "Existing_Order_Type__c",
        "Reason_for_cancellation__c",
        "Cancellation_Order_Notes__c",
        "Special_Terms__c",
        "Total_Number_of_Locations_for_this_order__c",
        "Location_I_D__c",
        "Billing_Start_Date1__c",
        "Chargify_Subscription_ID__c",
    }
)
CANCELLATION_ORDER_RECORD_TYPE_ALIASES = (
    "Existing_Customer_Cancellation_Order",
    "Existing Customer Cancellation Order",
    "Existing_Customer_Cancellation",
    "Existing Customer Cancellation",
)
CANCELLATION_ORDER_TYPE_LABEL = "Existing Customer Cancellation Order"
CANCELLATION_ORDER_FORMULA_LABEL = "Cancellation Order"
LOCATION_LIFECYCLE_ORDER_ACTIONS = frozenset(
    {"reactivate_existing_location", "add_additional_location"}
)
LOCATION_LIFECYCLE_ORDER_RECORD_TYPE_ALIASES = {
    "reactivate_existing_location": (
        "Re_activate_an_Existing_Location",
        "Reactivate_an_Existing_Location",
        "Re-activate an Existing Location",
        "Reactivate an Existing Location",
    ),
    "within_3_months": (
        "Within_the_3_months",
        "Within_the_3_months_Order",
        "Within the 3-months",
        "Within the 3 months",
        "Within 3 Months",
    ),
    "existing_additional": (
        "Existing_and_New_Additional_Customer_Order",
        "Existing_and__New__Additional_Customer_Order",
        "Existing and (New) Additional Customer Order",
        "Existing and New Additional Customer Order",
    ),
}
LOCATION_LIFECYCLE_ORDER_TYPE_LABELS = {
    "reactivate_existing_location": "Re-activate an Existing Location",
    "within_3_months": "Within the 3-months",
    "existing_additional": "Existing and (New) Additional Customer Order",
}
LOCATION_LIFECYCLE_ACTION_TYPE_LABELS = {
    "reactivate_existing_location": "Re-activate an Existing Location",
    "add_additional_location": "New Location",
}
FORBIDDEN_AGENT_ORDER_TYPE_LABEL = "New Customer Order"
NOVA_INTEGRATED_MERCHANT_PROVIDERS = (
    "Worldpay",
    "Creditcall",
    "Authorize.net",
    "Propelr",
)
CANCELLATION_REASON_ALIASES = {
    "business closed": "Business / Location Closing",
    "business closing": "Business / Location Closing",
    "business closure": "Business / Location Closing",
    "business location closing": "Business / Location Closing",
    "location closed": "Business / Location Closing",
    "location closing": "Business / Location Closing",
    "out of business": "Business / Location Closing",
    "store closed": "Business / Location Closing",
    "store closing": "Business / Location Closing",
    "switched to a competitor": "Pricing (Moved to Competition)",
    "switched to competitor": "Pricing (Moved to Competition)",
    "switch to a competitor": "Pricing (Moved to Competition)",
    "switch to competitor": "Pricing (Moved to Competition)",
    "moved to competition": "Pricing (Moved to Competition)",
    "competitor pricing": "Pricing (Moved to Competition)",
}
ACCOUNT_CANCELLATION_RE = re.compile(
    r"\b(?:cancel(?:l?ed|l?ing|lation)?|close(?:d|ing)?|deactivat(?:e|ed|ing|ion)|"
    r"terminat(?:e|ed|ing|ion))\b.{0,80}"
    r"\b(?:account|location|service|subscription|nova\s+pos)\b|"
    r"\b(?:account|location|service|subscription|nova\s+pos)\b.{0,80}"
    r"\b(?:cancel(?:l?ed|l?ing|lation)?|close(?:d|ing)?|deactivat(?:e|ed|ing|ion)|"
    r"terminat(?:e|ed|ing|ion))\b|"
    r"(?:^|\n)\s*(?:t?old|asked)\s+(?:me|us)\s+to\s+"
    r"(?:close|cancel)\s+(?:it|the\s+(?:account|service|subscription))\b",
    re.IGNORECASE | re.DOTALL,
)


class SalesforceScopeError(ValueError):
    """A request exceeded the fixed business-operation scope."""


class SalesforceUnavailableError(RuntimeError):
    """The scoped provider connection is unavailable."""


class SalesforceDefinitiveRejectionError(SalesforceUnavailableError):
    """Salesforce returned a definitive no-commit client rejection."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = int(status_code)


@dataclass(frozen=True)
class SalesforceSettings:
    instance_url: str
    login_url: str
    client_id: str
    client_secret: str
    username: str
    password: str
    access_token: str
    use_client_credentials: bool
    api_version: str = "54.0"
    journal_path: Path = Path("/var/lib/nova/broker/salesforce/operations.jsonl")

    @classmethod
    def from_env_file(cls, path: str | Path) -> "SalesforceSettings":
        values = {key: str(value or "").strip() for key, value in dotenv_values(path).items()}
        return cls._from_values(values)

    @classmethod
    def from_environment(cls) -> "SalesforceSettings":
        """Read only the fixed Salesforce credential names from the broker environment."""

        names = (
            "SALESFORCE_INSTANCE_URL",
            "SALESFORCE_LOGIN_URL",
            "SALESFORCE_CLIENT_ID",
            "SALESFORCE_CLIENT_SECRET",
            "SALESFORCE_USERNAME",
            "SALESFORCE_PASSWORD",
            "SALESFORCE_ACCESS_TOKEN",
            "SALESFORCE_USE_CLIENT_CREDENTIALS",
            "SALESFORCE_API_VERSION",
            "SALESFORCE_OPERATION_JOURNAL_PATH",
        )
        return cls._from_values({name: os.getenv(name, "") for name in names})

    @classmethod
    def _from_values(cls, values: dict[str, str]) -> "SalesforceSettings":
        api_version = values.get("SALESFORCE_API_VERSION") or "54.0"
        if not re.fullmatch(r"\d{2,3}\.0", api_version):
            api_version = "54.0"
        return cls(
            instance_url=(values.get("SALESFORCE_INSTANCE_URL") or "").rstrip("/"),
            login_url=(values.get("SALESFORCE_LOGIN_URL") or "https://login.salesforce.com").rstrip("/"),
            client_id=values.get("SALESFORCE_CLIENT_ID") or "",
            client_secret=values.get("SALESFORCE_CLIENT_SECRET") or "",
            username=values.get("SALESFORCE_USERNAME") or "",
            password=values.get("SALESFORCE_PASSWORD") or "",
            access_token=values.get("SALESFORCE_ACCESS_TOKEN") or "",
            use_client_credentials=(values.get("SALESFORCE_USE_CLIENT_CREDENTIALS") or "").lower()
            in {"1", "true", "yes", "on"},
            api_version=api_version,
            journal_path=Path(
                values.get("SALESFORCE_OPERATION_JOURNAL_PATH")
                or "/var/lib/nova/broker/salesforce/operations.jsonl"
            ),
        )


class ScopedSalesforceClient:
    """Salesforce client with no generic query, REST, metadata, or delete method."""

    def __init__(
        self,
        settings: SalesforceSettings,
        *,
        session: requests.Session | None = None,
        internal_communication_journal_path: str | Path | None = None,
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self._token = settings.access_token
        self._instance_url = settings.instance_url
        self._expires_at = 0.0
        self._internal_communication_journal_path = internal_communication_journal_path

    def capability_status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "accessMode": "typed_operations_only",
            "credentialsConfigured": bool(
                self.settings.access_token
                or (
                    self.settings.client_id
                    and self.settings.client_secret
                    and (self.settings.username and self.settings.password or self.settings.use_client_credentials)
                )
            ),
            "allowedObjects": ["Account", "Contact", "NovaPOS_Ticket__c", "NovaPOS_Order__c", "NovaPOS_Location__c"],
            "adminSurfacesExposed": False,
            "deleteExposed": False,
            "genericQueryExposed": False,
        }

    def _resolve_nova_sql_account(self, company_username: str) -> dict[str, str]:
        """Resolve one SQL login internally without exposing credential fields as a tool."""
        clean_username = str(company_username or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{1,80}", clean_username):
            raise SalesforceScopeError("company_username must be an exact Nova company username")
        escaped = _escape_soql(clean_username)
        result = self._query(
            "SELECT Id,Company_Username__c,Company_Password__c,"
            "Company_Password_Encyrpted__c,iPad_Company_Password__c,"
            "Account_Blocked__c,Database_Deleted__c FROM Account "
            f"WHERE Company_Username__c = '{escaped}' LIMIT 2"
        )
        records = [record for record in result.get("records", []) if isinstance(record, dict)]
        if len(records) != 1:
            raise SalesforceScopeError("company_username did not resolve to exactly one Salesforce account")
        record = records[0]
        if record.get("Account_Blocked__c") is True or record.get("Database_Deleted__c") is True:
            raise SalesforceScopeError("Nova SQL account is blocked or deleted")
        password = next(
            (
                str(record.get(field) or "")
                for field in (
                    "Company_Password__c",
                    "Company_Password_Encyrpted__c",
                    "iPad_Company_Password__c",
                )
                if str(record.get(field) or "")
            ),
            "",
        )
        if not password:
            raise SalesforceScopeError("Nova SQL account has no configured database credential")
        return {
            "account_id": str(record.get("Id") or ""),
            "company_username": clean_username,
            "password": password,
        }

    def api_customer_email_cohort(self, api_accounts: list[dict[str, Any]]) -> dict[str, Any]:
        """Apply fixed Salesforce account, location, and email checks to POS_Main API users."""

        candidates: dict[str, dict[str, Any]] = {}
        for raw in api_accounts[:5_000]:
            username = str(raw.get("companyUsername") or "").strip()
            if not re.fullmatch(r"[A-Za-z0-9_]{1,80}", username):
                continue
            key = username.casefold()
            candidates[key] = {
                "companyUsername": username,
                "databaseName": str(raw.get("databaseName") or "").strip()[:255],
                "apiExpirationDate": str(raw.get("apiExpirationDate") or "").strip()[:64],
            }

        accounts_by_username: dict[str, list[dict[str, Any]]] = {}
        usernames = [item["companyUsername"] for item in candidates.values()]
        for chunk in _chunks(usernames, 100):
            values = ",".join(f"'{_escape_soql(value)}'" for value in chunk)
            result = self._query(
                "SELECT Id,Name,Company_Username__c,Email_Address__c,recurly__Email__c,"
                "NovaPOS_Active__c,Account_Blocked__c,Database_Deleted__c,Fake_Account__c "
                f"FROM Account WHERE Company_Username__c IN ({values})"
            )
            for record in result.get("records", []):
                if not isinstance(record, dict):
                    continue
                key = str(record.get("Company_Username__c") or "").strip().casefold()
                if key in candidates:
                    accounts_by_username.setdefault(key, []).append(record)

        eligible_accounts: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        exclusions = {
            "noSalesforceAccount": 0,
            "ambiguousSalesforceAccount": 0,
            "inactiveAccount": 0,
            "blockedDeletedOrTestAccount": 0,
            "noActiveLocation": 0,
            "noValidEmail": 0,
        }
        for username_key, candidate in candidates.items():
            records = accounts_by_username.get(username_key, [])
            if not records:
                exclusions["noSalesforceAccount"] += 1
                continue
            if len(records) != 1:
                exclusions["ambiguousSalesforceAccount"] += 1
                continue
            account = records[0]
            try:
                active_account_locations = float(account.get("NovaPOS_Active__c") or 0)
            except (TypeError, ValueError):
                active_account_locations = 0
            if active_account_locations <= 0:
                exclusions["inactiveAccount"] += 1
                continue
            if any(
                account.get(field) is True
                for field in ("Account_Blocked__c", "Database_Deleted__c", "Fake_Account__c")
            ):
                exclusions["blockedDeletedOrTestAccount"] += 1
                continue
            account_id = str(account.get("Id") or "")
            if not SALESFORCE_ID.fullmatch(account_id):
                exclusions["ambiguousSalesforceAccount"] += 1
                continue
            eligible_accounts[account_id] = (candidate, account)

        active_location_counts: dict[str, int] = {}
        for chunk in _chunks(list(eligible_accounts), 100):
            values = ",".join(f"'{value}'" for value in chunk)
            result = self._query(
                "SELECT Account__c,COUNT(Id) activeLocationCount FROM NovaPOS_Location__c "
                f"WHERE Account__c IN ({values}) AND Status__c = 'Active' GROUP BY Account__c"
            )
            for record in result.get("records", []):
                if not isinstance(record, dict):
                    continue
                account_id = str(record.get("Account__c") or "")
                try:
                    count = int(record.get("activeLocationCount") or 0)
                except (TypeError, ValueError):
                    count = 0
                if account_id in eligible_accounts and count > 0:
                    active_location_counts[account_id] = count

        recipients: dict[str, dict[str, Any]] = {}
        for account_id, (candidate, account) in eligible_accounts.items():
            active_location_count = active_location_counts.get(account_id, 0)
            if active_location_count < 1:
                exclusions["noActiveLocation"] += 1
                continue
            email = next(
                (
                    str(account.get(field) or "").strip()
                    for field in ("Email_Address__c", "recurly__Email__c")
                    if EMAIL.fullmatch(str(account.get(field) or "").strip())
                ),
                "",
            )
            if not email:
                exclusions["noValidEmail"] += 1
                continue
            entry = recipients.setdefault(
                email.casefold(),
                {
                    "emailAddress": email,
                    "accounts": [],
                },
            )
            entry["accounts"].append(
                {
                    "accountId": account_id,
                    "accountName": str(account.get("Name") or "")[:255],
                    "companyUsername": candidate["companyUsername"],
                    "databaseName": candidate["databaseName"],
                    "apiExpirationDate": candidate["apiExpirationDate"],
                    "activeLocationCount": active_location_count,
                }
            )

        ordered_recipients = sorted(recipients.values(), key=lambda item: item["emailAddress"].casefold())
        return {
            "ok": True,
            "verified": True,
            "filters": {
                "apiAccess": "ApiExpirationDate > SYSUTCDATETIME()",
                "accountStatus": "NovaPOS_Active__c > 0",
                "accountSafety": "not blocked, database-deleted, or fake",
                "activeLocations": "at least one NovaPOS_Location__c with Status__c = Active",
                "email": "valid Email_Address__c, falling back to recurly__Email__c",
                "deduplication": "case-insensitive email address",
            },
            "eligibleAccountCount": sum(len(item["accounts"]) for item in ordered_recipients),
            "recipientCount": len(ordered_recipients),
            "recipients": ordered_recipients,
            "exclusions": exclusions,
        }

    def lookup(self, kind: str, value: str, *, account_id: str = "", limit: int = 10) -> dict[str, Any]:
        clean_kind = str(kind or "").strip().lower()
        if clean_kind not in LOOKUP_FIELDS:
            raise SalesforceScopeError("Lookup kind is not allowed")
        clean_value = _bounded(value, "value", 255)
        clean_account = _optional_id(account_id, "account_id")
        limit = max(1, min(int(limit), 25))
        object_name, fields = LOOKUP_FIELDS[clean_kind]
        if SALESFORCE_ID.fullmatch(clean_value):
            where = f"Id = '{clean_value}'"
        else:
            escaped = _escape_soql(clean_value)
            if clean_kind == "ticket":
                where = f"Name = '{escaped}'"
            elif clean_kind == "account":
                if NOVA_ID.fullmatch(clean_value):
                    where = f"Nova_ID__c = '{escaped}'"
                else:
                    where = (
                        f"(Name LIKE '%{escaped}%' OR Company_Username__c = '{escaped}' "
                        f"OR Nova_ID__c = '{escaped}')"
                    )
            elif clean_kind == "contact":
                where = f"(Name LIKE '%{escaped}%' OR Email = '{escaped}' OR Phone = '{escaped}')"
            elif clean_kind == "location":
                where = f"Name LIKE '%{escaped}%'"
            else:
                where = f"Name = '{escaped}'"
        if clean_account:
            account_field = "AccountId" if clean_kind == "contact" else "Account__c"
            where = f"({where}) AND {account_field} = '{clean_account}'"
        result = self._query(f"SELECT {fields} FROM {object_name} WHERE {where} LIMIT {limit}")
        return {"ok": True, "kind": clean_kind, "records": result.get("records", [])[:limit]}

    def read_account_360(
        self,
        search: str,
        *,
        contacts_limit: int = 100,
        locations_limit: int = 250,
        tickets_limit: int = 250,
    ) -> dict[str, Any]:
        """Resolve one Account and return its fixed relationship view without exposing SOQL."""

        clean_search = _bounded(search, "search", 255)
        clean_contacts_limit = max(1, min(int(contacts_limit), 500))
        clean_locations_limit = max(1, min(int(locations_limit), 500))
        clean_tickets_limit = max(1, min(int(tickets_limit), 500))
        escaped = _escape_soql(clean_search)
        is_record_id = bool(SALESFORCE_ID.fullmatch(clean_search))

        if is_record_id:
            account_where = f"Id = '{clean_search}'"
            contact_where = f"Id = '{clean_search}'"
            location_where = f"Id = '{clean_search}'"
            ticket_where = f"Id = '{clean_search}'"
        else:
            if NOVA_ID.fullmatch(clean_search):
                account_where = f"Nova_ID__c = '{escaped}'"
            else:
                account_where = (
                    f"(Name LIKE '%{escaped}%' OR Company_Username__c = '{escaped}' "
                    f"OR Nova_ID__c = '{escaped}' OR Phone = '{escaped}' "
                    f"OR Phone_II__c = '{escaped}')"
                )
            contact_where = (
                f"(Name = '{escaped}' OR Email = '{escaped}' OR Phone = '{escaped}' "
                f"OR MobilePhone = '{escaped}')"
            )
            location_where = f"Name = '{escaped}'"
            if clean_search.isdigit():
                location_where = f"({location_where} OR Location_ID__c = {int(clean_search)})"
            ticket_where = f"Name = '{escaped}'"

        direct_result = self._query(
            f"SELECT {ACCOUNT_360_ACCOUNT_FIELDS} FROM Account WHERE {account_where} LIMIT 26"
        )
        direct_accounts = [
            dict(record) for record in direct_result.get("records", []) if isinstance(record, dict)
        ][:26]
        direct_exact = [
            record
            for record in direct_accounts
            if _account_360_account_is_exact(record, clean_search, is_record_id=is_record_id)
        ]

        contact_matches = self._query(
            "SELECT Id,Name,AccountId,Email,Phone,MobilePhone FROM Contact "
            f"WHERE AccountId != null AND {contact_where} LIMIT 26"
        ).get("records", [])
        location_matches = self._query(
            "SELECT Id,Name,Account__c,Location_ID__c FROM NovaPOS_Location__c "
            f"WHERE Account__c != null AND {location_where} LIMIT 26"
        ).get("records", [])
        ticket_matches = self._query(
            "SELECT Id,Name,Account__c FROM NovaPOS_Ticket__c "
            f"WHERE Account__c != null AND {ticket_where} LIMIT 26"
        ).get("records", [])

        related_sources: dict[str, set[str]] = {}
        for source, records, account_field in (
            ("contact", contact_matches, "AccountId"),
            ("location", location_matches, "Account__c"),
            ("ticket", ticket_matches, "Account__c"),
        ):
            for record in records:
                if not isinstance(record, dict):
                    continue
                account_id = str(record.get(account_field) or "").strip()
                if SALESFORCE_ID.fullmatch(account_id):
                    related_sources.setdefault(account_id, set()).add(source)

        accounts_by_id = {
            str(record.get("Id") or ""): record
            for record in direct_accounts
            if SALESFORCE_ID.fullmatch(str(record.get("Id") or ""))
        }
        missing_account_ids = sorted(set(related_sources) - set(accounts_by_id))
        if missing_account_ids:
            values = ",".join(f"'{account_id}'" for account_id in missing_account_ids[:25])
            related_result = self._query(
                f"SELECT {ACCOUNT_360_ACCOUNT_FIELDS} FROM Account WHERE Id IN ({values}) LIMIT 26"
            )
            for record in related_result.get("records", []):
                if not isinstance(record, dict):
                    continue
                account_id = str(record.get("Id") or "")
                if SALESFORCE_ID.fullmatch(account_id):
                    accounts_by_id[account_id] = dict(record)

        resolved_account: dict[str, Any] | None = None
        resolution_source = ""
        if len(direct_exact) == 1:
            resolved_account = direct_exact[0]
            resolution_source = "account"
        elif len(direct_exact) > 1:
            resolution_source = "ambiguous_account"
        elif len(related_sources) == 1:
            related_account_id = next(iter(related_sources))
            resolved_account = accounts_by_id.get(related_account_id)
            resolution_source = "+".join(sorted(related_sources[related_account_id]))
        elif len(related_sources) > 1:
            resolution_source = "ambiguous_related_record"
        elif len(accounts_by_id) == 1:
            resolved_account = next(iter(accounts_by_id.values()))
            resolution_source = "unique_account_name_match"
        elif len(accounts_by_id) > 1:
            resolution_source = "ambiguous_account_matches"

        if resolved_account is None:
            candidates = [
                _account_360_candidate(record, related_sources.get(account_id, set()))
                for account_id, record in sorted(accounts_by_id.items())
            ][:25]
            return {
                "ok": True,
                "resolved": False,
                "search": clean_search,
                "reason": resolution_source or "not_found",
                "candidates": candidates,
                "candidateCount": len(candidates),
                "readOnly": True,
                "writesPerformed": False,
            }

        account_id = _required_id(str(resolved_account.get("Id") or ""), "resolved account id")
        contact_result = self._query(
            f"SELECT {ACCOUNT_360_CONTACT_FIELDS} FROM Contact WHERE AccountId = '{account_id}' "
            f"ORDER BY LastName,FirstName,Id LIMIT {clean_contacts_limit + 1}"
        )
        location_result = self._query(
            f"SELECT {ACCOUNT_360_LOCATION_FIELDS} FROM NovaPOS_Location__c "
            f"WHERE Account__c = '{account_id}' ORDER BY Location_ID__c,Id "
            f"LIMIT {clean_locations_limit + 1}"
        )
        ticket_result = self._query(
            f"SELECT {ACCOUNT_360_TICKET_FIELDS} FROM NovaPOS_Ticket__c "
            f"WHERE Account__c = '{account_id}' ORDER BY CreatedDate DESC "
            f"LIMIT {clean_tickets_limit + 1}"
        )

        primary_contact_id = str(resolved_account.get("PrimaryContact__c") or "")
        contacts = [
            _bounded_record(record)
            for record in contact_result.get("records", [])[:clean_contacts_limit]
            if isinstance(record, dict)
        ]
        for contact in contacts:
            contact["isPrimaryContact"] = bool(
                primary_contact_id and str(contact.get("Id") or "") == primary_contact_id
            )
        locations = [
            _bounded_record(record)
            for record in location_result.get("records", [])[:clean_locations_limit]
            if isinstance(record, dict)
        ]
        tickets = [
            _bounded_record(record)
            for record in ticket_result.get("records", [])[:clean_tickets_limit]
            if isinstance(record, dict)
        ]

        account = dict(resolved_account)
        owner = account.pop("Owner", None)
        nova_account_manager = account.pop("Nova_Account_Manager__r", None)
        primary_contact = account.pop("PrimaryContact__r", None)
        account.pop("attributes", None)
        return {
            "ok": True,
            "resolved": True,
            "verified": True,
            "search": clean_search,
            "resolutionSource": resolution_source,
            "account": _bounded_record(account),
            "owner": _bounded_record(owner) if isinstance(owner, dict) else None,
            "novaAccountManager": (
                _bounded_record(nova_account_manager) if isinstance(nova_account_manager, dict) else None
            ),
            "primaryContact": _bounded_record(primary_contact) if isinstance(primary_contact, dict) else None,
            "contacts": contacts,
            "locations": locations,
            "tickets": tickets,
            "counts": {
                "contactsReturned": len(contacts),
                "locationsReturned": len(locations),
                "ticketsReturned": len(tickets),
            },
            "truncated": {
                "contacts": len(contact_result.get("records", [])) > clean_contacts_limit,
                "locations": len(location_result.get("records", [])) > clean_locations_limit,
                "tickets": len(ticket_result.get("records", [])) > clean_tickets_limit,
            },
            "readOnly": True,
            "writesPerformed": False,
        }

    def read_ticket(self, ticket_id: str) -> dict[str, Any]:
        clean_id = _required_id(ticket_id, "ticket_id")
        record = self._request("GET", f"/sobjects/NovaPOS_Ticket__c/{clean_id}")
        return {"ok": True, "record": _bounded_record(record)}

    def verify_support_email_ticket_claim(
        self,
        *,
        ticket_id: str,
        ticket_number: str,
        account_id: str,
        record_type: str,
        source_key: str,
        allowed_record_types: Collection[str],
    ) -> dict[str, Any]:
        """Compare one fixed support-email ticket claim and return no ticket contents."""

        clean_ticket_id = _required_id(ticket_id, "ticket_id")
        clean_ticket_number = _bounded(ticket_number, "ticket_number", 32)
        clean_account_id = _required_id(account_id, "account_id")
        clean_record_type = _bounded(record_type, "record_type", 255)
        if clean_record_type not in frozenset(allowed_record_types):
            raise SalesforceScopeError("record_type is outside the support-ticket lane")
        clean_source_key = _bounded(source_key, "source_key", 255)
        result = self._query(
            "SELECT Id,Name,Account__c,Account__r.Id,Account__r.Name,"
            "Account__r.Fake_Account__c,RecordType.Name,Is_Closed__c "
            "FROM NovaPOS_Ticket__c "
            f"WHERE Id = '{clean_ticket_id}' LIMIT 1"
        )
        records = [
            record for record in result.get("records", []) if isinstance(record, dict)
        ]
        if len(records) != 1:
            raise SalesforceScopeError(
                "ticket_id did not resolve to exactly one Salesforce ticket"
            )
        record = records[0]
        record_type_value = (
            record.get("RecordType")
            if isinstance(record.get("RecordType"), dict)
            else {}
        )
        account = (
            record.get("Account__r")
            if isinstance(record.get("Account__r"), dict)
            else {}
        )
        return {
            "ticketIdMatches": str(record.get("Id") or "").strip()
            == clean_ticket_id,
            "ticketNumberMatches": str(record.get("Name") or "").strip()
            == clean_ticket_number,
            "accountIdMatches": str(record.get("Account__c") or "").strip()
            == clean_account_id,
            "recordTypeMatches": str(record_type_value.get("Name") or "").strip()
            == clean_record_type,
            "accountEligible": _support_email_account_is_eligible(
                account,
                expected_account_id=clean_account_id,
            ),
            "sourceKeyMatches": self._support_email_ticket_journal_matches(
                clean_ticket_id,
                clean_source_key,
                source_prefix="support-email",
            ),
            "isClosed": (
                record.get("Is_Closed__c")
                if isinstance(record.get("Is_Closed__c"), bool)
                else None
            ),
        }

    def verify_billing_closure_email_ticket_claim(
        self,
        *,
        ticket_id: str,
        ticket_number: str,
        account_id: str,
        record_type: str,
        source_key: str,
        file_name: str,
        sha256: str,
    ) -> dict[str, Any]:
        """Compare one closure-email ticket and attachment without returning customer contents."""

        allowed_record_types = {
            "1. NOVA Classic",
            "2. Nova Wave",
            "3. Billing",
        }
        clean_ticket_id = _required_id(ticket_id, "ticket_id")
        clean_ticket_number = _bounded(ticket_number, "ticket_number", 32)
        clean_account_id = _required_id(account_id, "account_id")
        clean_record_type = _bounded(record_type, "record_type", 255)
        if clean_record_type not in allowed_record_types:
            raise SalesforceScopeError("record_type is outside the closure-email ticket scope")
        clean_source_key = str(source_key or "").strip()
        if clean_source_key:
            source_email_id = clean_source_key.removeprefix("billing-closure-email:")
            if (
                clean_source_key != f"billing-closure-email:{source_email_id}"
                or not SUPPORT_EMAIL_SOURCE_ID.fullmatch(source_email_id)
            ):
                raise SalesforceScopeError("source_key is outside the closure-email namespace")
        clean_name, clean_digest = _validated_cancellation_email_identity(file_name, sha256)

        result = self._query(
            "SELECT Id,Name,Account__c,Account__r.Id,Account__r.Name,"
            "Account__r.Fake_Account__c,RecordType.Name,Is_Closed__c "
            "FROM NovaPOS_Ticket__c "
            f"WHERE Id = '{clean_ticket_id}' LIMIT 1"
        )
        records = [
            record for record in result.get("records", []) if isinstance(record, dict)
        ]
        if len(records) != 1:
            raise SalesforceScopeError(
                "ticket_id did not resolve to exactly one Salesforce ticket"
            )
        record = records[0]
        record_type_value = (
            record.get("RecordType")
            if isinstance(record.get("RecordType"), dict)
            else {}
        )
        account = (
            record.get("Account__r")
            if isinstance(record.get("Account__r"), dict)
            else {}
        )
        source_key_matches = True
        if clean_source_key:
            source_key_matches = self._support_email_ticket_journal_matches(
                clean_ticket_id,
                clean_source_key,
                source_prefix="billing-closure-email",
            )
        attachment = self.ticket_attachment_status(
            clean_ticket_id,
            clean_name,
            clean_digest,
            allowed_record_types=allowed_record_types,
        )
        return {
            "ticketIdMatches": str(record.get("Id") or "").strip()
            == clean_ticket_id,
            "ticketNumberMatches": str(record.get("Name") or "").strip()
            == clean_ticket_number,
            "accountIdMatches": str(record.get("Account__c") or "").strip()
            == clean_account_id,
            "recordTypeMatches": str(record_type_value.get("Name") or "").strip()
            == clean_record_type,
            "accountEligible": _support_email_account_is_eligible(
                account,
                expected_account_id=clean_account_id,
            ),
            "sourceKeyMatches": source_key_matches,
            "attachmentDigestMatches": attachment.get("duplicate") is True,
            "attachmentTitleConflict": attachment.get("conflictingTitle") is True,
            "isClosed": (
                record.get("Is_Closed__c")
                if isinstance(record.get("Is_Closed__c"), bool)
                else None
            ),
        }

    def ticket_scope(self, ticket_id: str) -> dict[str, str]:
        """Resolve the authoritative record type used by lane write policy."""

        clean_id = _required_id(ticket_id, "ticket_id")
        result = self._query(
            "SELECT Id,RecordTypeId,RecordType.Name FROM NovaPOS_Ticket__c "
            f"WHERE Id = '{clean_id}' LIMIT 1"
        )
        records = [record for record in result.get("records", []) if isinstance(record, dict)]
        if len(records) != 1:
            raise SalesforceScopeError("ticket did not resolve to exactly one Salesforce record")
        record = records[0]
        record_type = record.get("RecordType") if isinstance(record.get("RecordType"), dict) else {}
        record_type_name = str(record_type.get("Name") or "").strip()
        if not record_type_name:
            raise SalesforceUnavailableError("Salesforce ticket record type readback was incomplete")
        return {
            "ticketId": clean_id,
            "recordTypeId": str(record.get("RecordTypeId") or ""),
            "recordTypeName": record_type_name,
        }

    def _assert_ticket_scope(
        self,
        ticket_id: str,
        allowed_record_types: Collection[str] | None,
    ) -> dict[str, str]:
        if not allowed_record_types:
            return {"ticketId": _required_id(ticket_id, "ticket_id")}
        scope = self.ticket_scope(ticket_id)
        if scope["recordTypeName"] not in frozenset(allowed_record_types):
            raise SalesforceScopeError("ticket record type is outside this agent lane")
        return scope

    def _ticket_opener_name(self, ticket_id: str) -> str:
        """Return the exact ticket opener used by the required close picklist."""

        clean_id = _required_id(ticket_id, "ticket_id")
        result = self._query(
            "SELECT Id,CreatedBy.Name FROM NovaPOS_Ticket__c "
            f"WHERE Id = '{clean_id}' LIMIT 1"
        )
        records = [record for record in result.get("records", []) if isinstance(record, dict)]
        if len(records) != 1:
            raise SalesforceScopeError("ticket did not resolve to exactly one Salesforce record")
        created_by = records[0].get("CreatedBy")
        opener_name = str(created_by.get("Name") or "").strip() if isinstance(created_by, dict) else ""
        if not opener_name:
            raise SalesforceUnavailableError("Salesforce ticket opener readback was incomplete")
        return _bounded(opener_name, "ticket opener", 255)

    def _resolve_ticket_closed_by_rep(
        self,
        ticket_id: str,
        existing_value: Any,
    ) -> str:
        """Choose one known closure rep that is active for the ticket record type."""

        clean_id = _required_id(ticket_id, "ticket_id")
        scope = self.ticket_scope(clean_id)
        record_type_id = _required_id(
            str(scope.get("recordTypeId") or ""),
            "ticket record type id",
        )
        result = self._request(
            "GET",
            (
                "/ui-api/object-info/NovaPOS_Ticket__c/picklist-values/"
                f"{record_type_id}/{TICKET_CLOSED_BY_REP_FIELD}"
            ),
        )
        active_values = {
            str(entry.get("value") or "").strip()
            for entry in (result.get("values", []) if isinstance(result, dict) else [])
            if isinstance(entry, dict) and entry.get("active") is not False
        }
        active_values.discard("")

        current = str(existing_value or "").strip()
        if current and current in active_values:
            return current

        opener = self._ticket_opener_name(clean_id)
        if opener in active_values:
            return opener
        if TICKET_CLOSED_BY_REP_FALLBACK in active_values:
            return TICKET_CLOSED_BY_REP_FALLBACK
        raise SalesforceScopeError(
            "No safe active Ticket Closed by Rep value is configured for this ticket record type"
        )

    def _ticket_closure_metadata(self, ticket_id: str) -> dict[str, Any]:
        """Read the exact closure fields required by the org validation rule."""

        clean_id = _required_id(ticket_id, "ticket_id")
        result = self._query(
            "SELECT Id,Is_Closed__c,Ticket_Closed_Date__c,Ticket_Closed_by_Rep__c "
            f"FROM NovaPOS_Ticket__c WHERE Id = '{clean_id}' LIMIT 1"
        )
        records = [record for record in result.get("records", []) if isinstance(record, dict)]
        if len(records) != 1:
            raise SalesforceScopeError("ticket did not resolve to exactly one Salesforce record")
        return records[0]

    def _assert_ticket_create_scope(
        self,
        record_type_id: str,
        allowed_record_types: Collection[str] | None,
    ) -> dict[str, str]:
        if not allowed_record_types:
            return {}
        clean_record_type_id = _required_id(record_type_id, "record_type_id")
        result = self._query(
            "SELECT Id,Name,SObjectType FROM RecordType "
            f"WHERE Id = '{clean_record_type_id}' AND SObjectType = 'NovaPOS_Ticket__c' LIMIT 1"
        )
        records = [record for record in result.get("records", []) if isinstance(record, dict)]
        if len(records) != 1:
            raise SalesforceScopeError("record_type_id is not an exact NovaPOS ticket record type")
        record_type_name = str(records[0].get("Name") or "").strip()
        if record_type_name not in frozenset(allowed_record_types):
            raise SalesforceScopeError("ticket record type is outside this agent lane")
        return {"recordTypeId": clean_record_type_id, "recordTypeName": record_type_name}

    def list_open_tickets(self, *, limit: int = 200) -> dict[str, Any]:
        """Return only the fixed Command Center board population, with a hard row ceiling."""

        clean_limit = max(1, min(int(limit), 500))
        source_row_ceiling = 2000
        fields = (
            "Id,Name,RecordType.Name,Account__c,Account__r.Name,Account__r.Company_Username__c,"
            "Contact__c,CreatedDate,LastModifiedDate,Is_Closed__c,Ticket_Closed_Date__c,"
            "Description__c,Billing_Notes_Internal__c,Tech_Main_Issue__c,Technical_Issue__c,"
            "NOVA_Wave_Issue__c,NOVA_Wave_Technical_Issue__c,Customer_Contact__c,"
            "NovaPOS_Location__c,Location_ID__c"
        )
        result = self._query(
            f"SELECT {fields} FROM NovaPOS_Ticket__c WHERE Is_Closed__c = false "
            "AND RecordType.Name IN ('1. NOVA Classic','2. Nova Wave','3. Billing') "
            f"ORDER BY CreatedDate DESC LIMIT {source_row_ceiling}"
        )
        records: list[dict[str, Any]] = []
        for raw in result.get("records", [])[:source_row_ceiling]:
            if not isinstance(raw, dict):
                continue
            account = raw.get("Account__r") if isinstance(raw.get("Account__r"), dict) else {}
            account_identity = " ".join(
                [str(account.get("Name") or ""), str(account.get("Company_Username__c") or "")]
            ).casefold()
            if any(marker in account_identity for marker in ("demo", "test", "template")):
                continue
            record_type = raw.get("RecordType") if isinstance(raw.get("RecordType"), dict) else {}
            record_type_name = str(record_type.get("Name") or "")
            technical_issue = str(
                raw.get("Technical_Issue__c") or raw.get("NOVA_Wave_Technical_Issue__c") or ""
            ).strip().casefold()
            if record_type_name in {"1. NOVA Classic", "2. Nova Wave"} and technical_issue in {
                "bug",
                "feature request",
            }:
                continue
            records.append(_bounded_record(raw))
            if len(records) >= clean_limit:
                break
        return {
            "ok": True,
            "records": records,
            "count": len(records),
            "rowCeiling": clean_limit,
            "sourceRowCeiling": source_row_ceiling,
            "filter": "open_nova_classic_wave_billing_non_demo_non_bug_feature",
        }

    def weekly_ticket_totals(self, *, start_utc: str, end_utc: str) -> dict[str, Any]:
        """Count the two support record types in one bounded UTC window."""

        clean_start, start_value = _weekly_utc_timestamp(start_utc, "start_utc")
        clean_end, end_value = _weekly_utc_timestamp(end_utc, "end_utc")
        if end_value <= start_value:
            raise SalesforceScopeError("end_utc must be after start_utc")
        if (end_value - start_value).total_seconds() > 31 * 86400:
            raise SalesforceScopeError("weekly ticket totals are limited to 31 days")
        result = self._query(
            "SELECT RecordType.Name record_type, COUNT(Id) total "
            "FROM NovaPOS_Ticket__c "
            f"WHERE CreatedDate >= {clean_start} AND CreatedDate < {clean_end} "
            "AND RecordType.Name IN ('1. NOVA Classic','2. Nova Wave') "
            "GROUP BY RecordType.Name"
        )
        totals = {"1. NOVA Classic": 0, "2. Nova Wave": 0}
        for raw in result.get("records", []):
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("record_type") or "").strip()
            if name in totals:
                totals[name] = max(0, int(raw.get("total") or 0))
        classic = totals["1. NOVA Classic"]
        wave = totals["2. Nova Wave"]
        return {
            "ok": True,
            "startUtc": clean_start,
            "endUtc": clean_end,
            "novaClassic": classic,
            "novaWave": wave,
            "total": classic + wave,
            "recordTypes": list(totals),
            "filter": "CreatedDate UTC window and exact Classic/Wave RecordType names only",
        }

    def support_quality_ticket_projection_rows(
        self,
        *,
        start_utc: str,
        end_utc: str,
    ) -> dict[str, Any]:
        """Return fixed ticket fields to the isolated runtime projection only."""

        for value, label in ((start_utc, "start_utc"), (end_utc, "end_utc")):
            try:
                supplied = datetime.fromisoformat(
                    str(value or "").strip().replace("Z", "+00:00")
                )
            except ValueError as exc:
                raise SalesforceScopeError(
                    f"{label} must be an ISO-8601 UTC timestamp"
                ) from exc
            if supplied.tzinfo is None or supplied.utcoffset() != timedelta(0):
                raise SalesforceScopeError(f"{label} must be UTC")
        clean_start, start_value = _weekly_utc_timestamp(start_utc, "start_utc")
        clean_end, end_value = _weekly_utc_timestamp(end_utc, "end_utc")
        if end_value <= start_value:
            raise SalesforceScopeError("end_utc must be after start_utc")
        if (end_value - start_value).total_seconds() > 8 * 86400:
            raise SalesforceScopeError("support quality ticket projection is limited to 8 days")
        record_types = ",".join(
            f"'{_escape_soql(value)}'" for value in SUPPORT_QUALITY_TICKET_RECORD_TYPES
        )
        result = self._query(
            f"SELECT {SUPPORT_QUALITY_TICKET_FIELDS} "
            "FROM NovaPOS_Ticket__c "
            f"WHERE CreatedDate >= {clean_start} AND CreatedDate < {clean_end} "
            f"AND RecordType.Name IN ({record_types}) "
            "ORDER BY CreatedDate ASC, Id ASC "
            f"LIMIT {SUPPORT_QUALITY_TICKET_ROW_CEILING}"
        )
        records = [
            record
            for record in result.get("records", [])
            if isinstance(record, dict)
        ][:SUPPORT_QUALITY_TICKET_ROW_CEILING]
        return {
            "startUtc": clean_start,
            "endUtc": clean_end,
            "records": records,
            "rowCeiling": SUPPORT_QUALITY_TICKET_ROW_CEILING,
            "rowLimitReached": len(records) >= SUPPORT_QUALITY_TICKET_ROW_CEILING,
            "readOnly": True,
            "writesPerformed": False,
        }

    def read_ticket_feed(self, ticket_id: str, *, limit: int = 8) -> dict[str, Any]:
        clean_id = _required_id(ticket_id, "ticket_id")
        clean_limit = max(1, min(int(limit), 20))
        result = self._request(
            "GET",
            f"/chatter/feeds/record/{clean_id}/feed-elements",
            params={"pageSize": clean_limit},
        )
        elements = result.get("elements", []) if isinstance(result, dict) else []
        return {
            "ok": True,
            "ticketId": clean_id,
            # Put the compact projection first so nested Chatter comments stay
            # visible instead of disappearing behind the generic depth bound.
            "posts": _compact_ticket_feed(elements[:clean_limit]),
            "elements": _bounded_record(elements[:clean_limit]),
            "count": min(len(elements), clean_limit),
        }

    def create_ticket(
        self,
        *,
        account_id: str,
        description: str,
        contact_id: str = "",
        location_id: str = "",
        record_type_id: str = "",
        main_issue: str = "",
        technical_issue: str = "",
        customer_contact_method: str = "",
        source_key: str = "",
        allowed_record_types: Collection[str] | None = None,
    ) -> dict[str, Any]:
        if str(source_key or "").strip():
            raise SalesforceScopeError(
                "source_key is private intake metadata and cannot be stored on a ticket"
            )
        scope = self._assert_ticket_create_scope(record_type_id, allowed_record_types)
        payload: dict[str, Any] = {
            "Account__c": _required_id(account_id, "account_id"),
            "Description__c": _bounded(description, "description", 131072),
        }
        _put_optional_id(payload, "Contact__c", contact_id)
        _put_optional_id(payload, "NovaPOS_Location__c", location_id)
        _put_optional_id(payload, "RecordTypeId", record_type_id)
        _put_optional_text(payload, "Tech_Main_Issue__c", main_issue, 255)
        _put_optional_text(payload, "Technical_Issue__c", technical_issue, 255)
        _put_optional_text(payload, "Customer_Contact__c", customer_contact_method, 255)
        created = self._request("POST", "/sobjects/NovaPOS_Ticket__c", json=payload)
        record_id = _required_id(str(created.get("id") or ""), "created ticket id")
        readback = self.read_ticket(record_id)
        return {
            "ok": True,
            "created": True,
            "id": record_id,
            "recordTypePolicy": scope,
            "readback": readback["record"],
        }

    def create_support_email_ticket(
        self,
        *,
        account_id: str,
        description: str,
        source_email_id: str,
        source_key: str,
        record_type_id: str,
        ticket_created_by: str,
        contact_id: str = "",
        location_id: str = "",
        main_issue: str = "",
        technical_issue: str = "",
        customer_contact_method: str = "",
        allowed_record_types: Collection[str],
        source_prefix: str = "support-email",
        operation_name: str = "support_email_ticket_create",
        idempotency_prefix: str = "support-email-ticket-create",
    ) -> dict[str, Any]:
        """Create or reuse one journaled support-email ticket and return bounded readback."""

        clean_account_id = _required_id(account_id, "account_id")
        clean_source_email_id = str(source_email_id or "").strip()
        if not SUPPORT_EMAIL_SOURCE_ID.fullmatch(clean_source_email_id):
            raise SalesforceScopeError("source_email_id is invalid")
        clean_source_prefix = str(source_prefix or "").strip()
        if clean_source_prefix not in {"support-email", "billing-closure-email"}:
            raise SalesforceScopeError("source_prefix is not an approved email-intake namespace")
        clean_operation_name = str(operation_name or "").strip()
        clean_idempotency_prefix = str(idempotency_prefix or "").strip()
        if (
            clean_operation_name
            not in {"support_email_ticket_create", "billing_closure_email_ticket_create"}
            or clean_idempotency_prefix
            not in {"support-email-ticket-create", "billing-closure-email-ticket-create"}
        ):
            raise SalesforceScopeError("email-intake operation identity is invalid")
        clean_source_key = _bounded(source_key, "source_key", 255)
        if clean_source_key != f"{clean_source_prefix}:{clean_source_email_id}":
            raise SalesforceScopeError(
                f"source_key must exactly match {clean_source_prefix}:<source_email_id>"
            )
        clean_description = _bounded(description, "description", 20_000)
        if SUPPORT_EMAIL_SOURCE_MARKER.search(clean_description):
            raise SalesforceScopeError(
                "description must not contain a Source key marker; "
                "source identity is retained only in the private operation journal"
            )
        clean_created_by = _bounded(
            ticket_created_by,
            "ticket_created_by",
            255,
        )
        if clean_created_by != "Darius Parlor":
            raise SalesforceScopeError(
                "ticket_created_by does not match the server-owned support-email value"
            )
        clean_record_type_id = _required_id(record_type_id, "record_type_id")
        scope = self._assert_ticket_create_scope(
            clean_record_type_id,
            allowed_record_types,
        )
        self._require_support_email_account_eligible(clean_account_id)
        active_created_by = self._resolve_support_email_ticket_created_by(
            clean_record_type_id,
            clean_created_by,
        )
        clean_contact_id = _optional_id(contact_id, "contact_id")
        clean_location_id = _optional_id(location_id, "location_id")
        self._require_support_email_linked_records(
            account_id=clean_account_id,
            contact_id=clean_contact_id,
            location_id=clean_location_id,
        )
        clean_main_issue = str(main_issue or "").strip()
        clean_technical_issue = str(technical_issue or "").strip()
        clean_contact_method = str(customer_contact_method or "").strip()
        if clean_main_issue:
            clean_main_issue = _bounded(clean_main_issue, "main_issue", 255)
        if clean_technical_issue:
            clean_technical_issue = _bounded(
                clean_technical_issue,
                "technical_issue",
                255,
            )
        if clean_contact_method:
            clean_contact_method = _bounded(
                clean_contact_method,
                "customer_contact_method",
                255,
            )

        expected = {
            "accountId": clean_account_id,
            "contactId": clean_contact_id,
            "locationId": clean_location_id,
            "recordTypeId": clean_record_type_id,
            "recordType": str(scope["recordTypeName"]),
            "mainIssue": clean_main_issue,
            "technicalIssue": clean_technical_issue,
            "customerContactMethod": clean_contact_method,
            "ticketCreatedBy": active_created_by,
            "accountEligible": True,
            "sourceEmailId": clean_source_email_id,
            "sourceKey": clean_source_key,
            "description": clean_description,
        }
        plan = {
            "operation": clean_operation_name,
            **expected,
            "descriptionSha256": hashlib.sha256(
                clean_description.encode("utf-8")
            ).hexdigest(),
        }
        plan_hash = _stable_plan_hash(plan)
        idempotency_key = (
            f"{clean_idempotency_prefix}:"
            + hashlib.sha256(clean_source_key.encode("utf-8")).hexdigest()[:32]
        )
        operation = clean_operation_name

        with self._salesforce_write_lock():
            prior = self._prior_salesforce_operation(idempotency_key)
            if prior is not None:
                prior_status = str(prior.get("status") or "").strip()
                identity_fields = (
                    ("operation", operation),
                    ("target", clean_source_key),
                )
                if any(
                    prior.get(field) != value
                    for field, value in identity_fields
                ):
                    raise SalesforceScopeError(
                        "The source-key idempotency journal belongs to a different "
                        "support-email ticket operation"
                    )
                if prior_status == "rejected":
                    # A definitive 4xx response proves the prior request did
                    # not commit, so a corrected plan can safely retry.
                    prior = None
            if prior is not None:
                prior_evidence = (
                    prior.get("evidence")
                    if isinstance(prior.get("evidence"), dict)
                    else {}
                )
                if prior.get("status") == "accepted":
                    prior_ticket_id = str(
                        prior_evidence.get("ticketId") or ""
                    ).strip()
                    if not prior_ticket_id:
                        raise SalesforceUnavailableError(
                            "Journaled support-email ticket evidence was incomplete"
                        )
                    receipt = self._support_email_ticket_creation_receipt(
                        self._support_email_ticket_record(prior_ticket_id),
                        expected=expected,
                    )
                    if not receipt["verified"]:
                        raise SalesforceUnavailableError(
                            "Journaled support-email ticket live readback did not match"
                        )
                    return {
                        **receipt,
                        "ok": True,
                        "created": False,
                        "duplicate": True,
                        "replayed": True,
                        "idempotencyKey": idempotency_key,
                        "writesPerformed": False,
                    }
                if prior.get("status") != "pending":
                    raise SalesforceUnavailableError(
                        "The support-email ticket journal state was invalid"
                    )

                prior_ticket_id = str(
                    prior_evidence.get("ticketId") or ""
                ).strip()
                if prior_ticket_id:
                    receipt = self._support_email_ticket_creation_receipt(
                        self._support_email_ticket_record(prior_ticket_id),
                        expected=expected,
                    )
                    if not receipt["verified"]:
                        raise SalesforceUnavailableError(
                            "Journaled support-email ticket live readback did not match"
                        )
                    result = {
                        **receipt,
                        "ok": True,
                        "created": False,
                        "duplicate": True,
                        "replayed": True,
                        "idempotencyKey": idempotency_key,
                        "writesPerformed": False,
                    }
                    self._complete_salesforce_operation(
                        idempotency_key,
                        operation,
                        clean_source_key,
                        plan_hash,
                        result,
                    )
                    return result
                post_attempted = prior_evidence.get("postAttempted")
                prior_plan_matches = prior.get("planHash") == plan_hash
                if post_attempted is not False:
                    try:
                        pending_age_seconds = max(
                            0,
                            int(time.time()) - int(prior.get("time") or 0),
                        )
                    except (TypeError, ValueError):
                        pending_age_seconds = 900
                    return {
                        "ok": False,
                        "verified": False,
                        "status": "uncertain",
                        "retryable": False,
                        "requiresReview": True,
                        "reasonCode": (
                            "post_outcome_unconfirmed"
                            if prior_plan_matches
                            else "post_outcome_plan_changed"
                        ),
                        "retryAfterSeconds": 0,
                        "pendingAgeSeconds": pending_age_seconds,
                        "created": False,
                        "duplicate": False,
                        "replayed": True,
                        "ticketId": str(
                            prior_evidence.get("ticketId") or ""
                        ).strip(),
                        "accountId": clean_account_id,
                        "accountEligible": True,
                        "recordTypeId": clean_record_type_id,
                        "recordType": expected["recordType"],
                        "ticketCreatedBy": active_created_by,
                        "sourceEmailId": clean_source_email_id,
                        "sourceKey": clean_source_key,
                        "idempotencyKey": idempotency_key,
                        "writesPerformed": False,
                    }
                # The journal proves no provider write was attempted, so a
                # corrected plan can safely replace the abandoned pre-write plan.
                prior = None

            self._journal_salesforce_operation(
                "pending",
                idempotency_key,
                operation,
                clean_source_key,
                plan_hash,
                {"postAttempted": False},
            )
            payload: dict[str, Any] = {
                "Account__c": clean_account_id,
                "RecordTypeId": clean_record_type_id,
                "Description__c": clean_description,
                "Ticket_Created_by__c": active_created_by,
            }
            _put_optional_id(payload, "Contact__c", clean_contact_id)
            _put_optional_id(payload, "NovaPOS_Location__c", clean_location_id)
            _put_optional_text(
                payload,
                "Tech_Main_Issue__c",
                clean_main_issue,
                255,
            )
            _put_optional_text(
                payload,
                "Technical_Issue__c",
                clean_technical_issue,
                255,
            )
            _put_optional_text(
                payload,
                "Customer_Contact__c",
                clean_contact_method,
                255,
            )
            # Record intent immediately before the one provider mutation. A
            # crash after this row is treated as uncertain until exact live
            # source-key readback resolves it.
            self._journal_salesforce_operation(
                "pending",
                idempotency_key,
                operation,
                clean_source_key,
                plan_hash,
                {"postAttempted": True},
            )
            try:
                created = self._request(
                    "POST",
                    "/sobjects/NovaPOS_Ticket__c",
                    json=payload,
                )
            except SalesforceDefinitiveRejectionError as exc:
                self._journal_salesforce_operation(
                    "rejected",
                    idempotency_key,
                    operation,
                    clean_source_key,
                    plan_hash,
                    {
                        "postAttempted": True,
                        "providerRejected": True,
                        "statusCode": exc.status_code,
                    },
                )
                return {
                    "ok": False,
                    "verified": False,
                    "status": "rejected",
                    "retryable": True,
                    "reasonCode": "provider_rejected_no_commit",
                    "created": False,
                    "duplicate": False,
                    "replayed": False,
                    "ticketId": "",
                    "accountId": clean_account_id,
                    "accountEligible": True,
                    "recordTypeId": clean_record_type_id,
                    "recordType": expected["recordType"],
                    "ticketCreatedBy": active_created_by,
                    "sourceEmailId": clean_source_email_id,
                    "sourceKey": clean_source_key,
                    "idempotencyKey": idempotency_key,
                    "writesPerformed": False,
                }
            ticket_id = _required_id(
                str(created.get("id") or ""),
                "created ticket id",
            )
            self._journal_salesforce_operation(
                "pending",
                idempotency_key,
                operation,
                clean_source_key,
                plan_hash,
                {"postAttempted": True, "ticketId": ticket_id},
            )
            receipt = self._support_email_ticket_creation_receipt(
                self._support_email_ticket_record(ticket_id),
                expected=expected,
            )
            if not receipt["verified"]:
                raise SalesforceUnavailableError(
                    "Support-email ticket create readback did not match; "
                    "do not retry until the private journal can recover the ticket"
                )
            result = {
                **receipt,
                "ok": True,
                "created": True,
                "duplicate": False,
                "replayed": False,
                "idempotencyKey": idempotency_key,
                "writesPerformed": True,
            }
            self._complete_salesforce_operation(
                idempotency_key,
                operation,
                clean_source_key,
                plan_hash,
                result,
            )
            return result

    def create_billing_closure_email_ticket(
        self,
        *,
        account_id: str,
        description: str,
        source_email_id: str,
        source_key: str,
        ticket_created_by: str,
        contact_id: str = "",
        location_id: str = "",
        main_issue: str = "",
        technical_issue: str = "",
        customer_contact_method: str = "",
        allowed_record_types: Collection[str],
    ) -> dict[str, Any]:
        """Create or reuse one exact source-keyed Billing closure-request ticket."""

        record_type_id = self._resolve_ticket_record_type_id("3. Billing")
        return self.create_support_email_ticket(
            account_id=account_id,
            description=description,
            source_email_id=source_email_id,
            source_key=source_key,
            record_type_id=record_type_id,
            ticket_created_by=ticket_created_by,
            contact_id=contact_id,
            location_id=location_id,
            main_issue=main_issue,
            technical_issue=technical_issue,
            customer_contact_method=customer_contact_method,
            allowed_record_types=allowed_record_types,
            source_prefix="billing-closure-email",
            operation_name="billing_closure_email_ticket_create",
            idempotency_prefix="billing-closure-email-ticket-create",
        )

    def _resolve_ticket_record_type_id(self, record_type_name: str) -> str:
        clean_name = _bounded(record_type_name, "record_type_name", 255)
        result = self._query(
            "SELECT Id,Name FROM RecordType "
            "WHERE SobjectType = 'NovaPOS_Ticket__c' AND IsActive = true "
            f"AND Name = '{_escape_soql(clean_name)}' LIMIT 2"
        )
        records = [
            record for record in result.get("records", []) if isinstance(record, dict)
        ]
        if len(records) != 1:
            raise SalesforceScopeError(
                "ticket record type did not resolve to exactly one active Salesforce record"
            )
        return _required_id(str(records[0].get("Id") or ""), "record type id")

    def _resolve_support_email_ticket_created_by(
        self,
        record_type_id: str,
        configured_value: str,
    ) -> str:
        clean_record_type_id = _required_id(record_type_id, "record_type_id")
        clean_value = _bounded(configured_value, "ticket_created_by", 255)
        result = self._request(
            "GET",
            (
                "/ui-api/object-info/NovaPOS_Ticket__c/picklist-values/"
                f"{clean_record_type_id}/Ticket_Created_by__c"
            ),
        )
        values = result.get("values", []) if isinstance(result, dict) else []
        matches = [
            entry
            for entry in values
            if isinstance(entry, dict)
            and entry.get("active") is not False
            and str(entry.get("value") or "").strip() == clean_value
        ]
        if len(matches) != 1:
            raise SalesforceScopeError(
                "The server-owned Ticket_Created_by__c value is not active "
                "for the selected support record type"
            )
        return clean_value

    def _require_support_email_account_eligible(self, account_id: str) -> None:
        clean_account_id = _required_id(account_id, "account_id")
        result = self._query(
            "SELECT Id,Name,Fake_Account__c FROM Account "
            f"WHERE Id = '{clean_account_id}' LIMIT 1"
        )
        records = [
            record
            for record in result.get("records", [])
            if isinstance(record, dict)
        ]
        if (
            len(records) != 1
            or not _support_email_account_is_eligible(
                records[0],
                expected_account_id=clean_account_id,
            )
        ):
            raise SalesforceScopeError(
                "The authoritative Salesforce Account is not eligible for "
                "support-email ticket creation"
            )

    def _require_support_email_linked_records(
        self,
        *,
        account_id: str,
        contact_id: str,
        location_id: str,
    ) -> None:
        clean_account_id = _required_id(account_id, "account_id")
        if contact_id:
            clean_contact_id = _required_id(contact_id, "contact_id")
            result = self._query(
                "SELECT Id,AccountId FROM Contact "
                f"WHERE Id = '{clean_contact_id}' LIMIT 1"
            )
            records = [
                record
                for record in result.get("records", [])
                if isinstance(record, dict)
            ]
            if (
                len(records) != 1
                or str(records[0].get("Id") or "").strip() != clean_contact_id
                or str(records[0].get("AccountId") or "").strip()
                != clean_account_id
            ):
                raise SalesforceScopeError(
                    "contact_id is not linked to the authoritative support-email Account"
                )
        if location_id:
            clean_location_id = _required_id(location_id, "location_id")
            result = self._query(
                "SELECT Id,Account__c FROM NovaPOS_Location__c "
                f"WHERE Id = '{clean_location_id}' LIMIT 1"
            )
            records = [
                record
                for record in result.get("records", [])
                if isinstance(record, dict)
            ]
            if (
                len(records) != 1
                or str(records[0].get("Id") or "").strip() != clean_location_id
                or str(records[0].get("Account__c") or "").strip()
                != clean_account_id
            ):
                raise SalesforceScopeError(
                    "location_id is not linked to the authoritative support-email Account"
                )

    def _support_email_ticket_record(self, ticket_id: str) -> dict[str, Any]:
        clean_id = _required_id(ticket_id, "ticket_id")
        result = self._query(
            "SELECT Id,Name,Account__c,Account__r.Id,Account__r.Name,"
            "Account__r.Fake_Account__c,Contact__c,NovaPOS_Location__c,"
            "RecordTypeId,RecordType.Name,Is_Closed__c,Ticket_Created_by__c,"
            "Tech_Main_Issue__c,Technical_Issue__c,Customer_Contact__c,"
            "Description__c FROM NovaPOS_Ticket__c "
            f"WHERE Id = '{clean_id}' LIMIT 1"
        )
        records = [
            record
            for record in result.get("records", [])
            if isinstance(record, dict)
        ]
        if len(records) != 1:
            raise SalesforceScopeError(
                "ticket_id did not resolve to exactly one Salesforce ticket"
            )
        return records[0]

    def _support_email_ticket_journal_matches(
        self,
        ticket_id: str,
        source_key: str,
        *,
        source_prefix: str,
    ) -> bool:
        """Verify private email-source provenance without reading ticket narrative."""

        clean_ticket_id = _required_id(ticket_id, "ticket_id")
        clean_source_key = _bounded(source_key, "source_key", 255)
        identities = {
            "support-email": (
                "support_email_ticket_create",
                "support-email-ticket-create",
            ),
            "billing-closure-email": (
                "billing_closure_email_ticket_create",
                "billing-closure-email-ticket-create",
            ),
        }
        clean_source_prefix = str(source_prefix or "").strip()
        identity = identities.get(clean_source_prefix)
        if identity is None:
            raise SalesforceScopeError("source_prefix is invalid")
        source_email_id = clean_source_key.removeprefix(
            f"{clean_source_prefix}:"
        )
        if (
            clean_source_key != f"{clean_source_prefix}:{source_email_id}"
            or not SUPPORT_EMAIL_SOURCE_ID.fullmatch(source_email_id)
        ):
            raise SalesforceScopeError("source_key is invalid")
        operation, idempotency_prefix = identity
        idempotency_key = (
            f"{idempotency_prefix}:"
            + hashlib.sha256(clean_source_key.encode("utf-8")).hexdigest()[:32]
        )
        prior = self._prior_salesforce_operation(idempotency_key)
        evidence = (
            prior.get("evidence")
            if isinstance(prior, dict)
            and isinstance(prior.get("evidence"), dict)
            else {}
        )
        return bool(
            isinstance(prior, dict)
            and prior.get("status") == "accepted"
            and prior.get("operation") == operation
            and prior.get("target") == clean_source_key
            and str(evidence.get("ticketId") or "").strip() == clean_ticket_id
        )

    def _support_email_ticket_creation_receipt(
        self,
        record: dict[str, Any],
        *,
        expected: dict[str, Any],
    ) -> dict[str, Any]:
        record_type_value = (
            record.get("RecordType")
            if isinstance(record.get("RecordType"), dict)
            else {}
        )
        description = str(record.get("Description__c") or "")
        account = (
            record.get("Account__r")
            if isinstance(record.get("Account__r"), dict)
            else {}
        )
        account_eligible = _support_email_account_is_eligible(
            account,
            expected_account_id=expected["accountId"],
        )
        expected_description = str(expected.get("description") or "")
        legacy_description = (
            f"{expected_description}\n\nSource key: {expected['sourceKey']}"
        )
        comparable_description = (
            expected_description
            if description == legacy_description
            else description
        )
        actual = {
            "accountId": str(record.get("Account__c") or "").strip(),
            "contactId": str(record.get("Contact__c") or "").strip(),
            "locationId": str(record.get("NovaPOS_Location__c") or "").strip(),
            "recordTypeId": str(record.get("RecordTypeId") or "").strip(),
            "recordType": str(record_type_value.get("Name") or "").strip(),
            "mainIssue": str(record.get("Tech_Main_Issue__c") or "").strip(),
            "technicalIssue": str(record.get("Technical_Issue__c") or "").strip(),
            "customerContactMethod": str(
                record.get("Customer_Contact__c") or ""
            ).strip(),
            "ticketCreatedBy": str(
                record.get("Ticket_Created_by__c") or ""
            ).strip(),
            "accountEligible": account_eligible,
            # Read-only compatibility for tickets created before source
            # identity moved into the private journal. New writes never add
            # the legacy marker.
            "description": comparable_description,
        }
        mismatch_fields = [
            field
            for field, expected_value in expected.items()
            if field
            not in {
                "sourceEmailId",
                "sourceKey",
            }
            and actual.get(field) != expected_value
        ]
        is_closed = record.get("Is_Closed__c")
        if is_closed is not False:
            mismatch_fields.append("isClosed")
        ticket_id = str(record.get("Id") or "").strip()
        ticket_number = str(record.get("Name") or "").strip()
        if not SALESFORCE_ID.fullmatch(ticket_id):
            mismatch_fields.append("ticketId")
        if not re.fullmatch(r"\d{5,12}", ticket_number):
            mismatch_fields.append("ticketNumber")
        verified = not mismatch_fields
        return {
            "verified": verified,
            "ticketId": ticket_id,
            "ticketNumber": ticket_number,
            "accountId": expected["accountId"],
            "contactId": expected["contactId"],
            "locationId": expected["locationId"],
            "recordTypeId": expected["recordTypeId"],
            "recordType": expected["recordType"],
            "mainIssue": expected["mainIssue"],
            "technicalIssue": expected["technicalIssue"],
            "ticketCreatedBy": expected["ticketCreatedBy"],
            "accountEligible": account_eligible,
            "sourceEmailId": expected["sourceEmailId"],
            "sourceKey": expected["sourceKey"],
            "isClosed": is_closed if isinstance(is_closed, bool) else None,
            "mismatchFields": sorted(set(mismatch_fields)),
            "readbackSource": "salesforce-live-ticket-by-id",
        }

    def update_ticket(
        self,
        ticket_id: str,
        fields: dict[str, Any],
        *,
        allowed_record_types: Collection[str] | None = None,
    ) -> dict[str, Any]:
        clean_id = _required_id(ticket_id, "ticket_id")
        self._assert_ticket_scope(clean_id, allowed_record_types)
        canonical_fields = dict(fields) if isinstance(fields, dict) else fields
        if isinstance(canonical_fields, dict) and {
            "Technical_Notes__c",
            "Description__c",
        }.intersection(canonical_fields):
            raise SalesforceScopeError("Ticket notes must be posted to Chatter")
        if (
            isinstance(canonical_fields, dict)
            and "Credit_Amount__c" in canonical_fields
            and set(allowed_record_types or ()) != {"3. Billing"}
        ):
            raise SalesforceScopeError("Credit_Amount__c is restricted to the billing lane")
        payload = _allowlisted_fields(canonical_fields, TICKET_UPDATE_FIELDS, "ticket")
        self._request("PATCH", f"/sobjects/NovaPOS_Ticket__c/{clean_id}", json=payload)
        readback = self.read_ticket(clean_id)
        return {"ok": True, "updated": True, "id": clean_id, "readback": readback["record"]}

    def payment_card_ticket_redaction_preview(
        self,
        ticket_id: str,
    ) -> dict[str, Any]:
        """Preview fixed-field and raw-text card redaction for one Billing ticket."""

        plan, _payload = self._payment_card_ticket_redaction_plan(ticket_id)
        return {
            "ok": True,
            "status": "preview",
            **plan,
            "planHash": _stable_plan_hash(plan),
            "writesPerformed": False,
        }

    def apply_payment_card_ticket_redaction(
        self,
        ticket_id: str,
        *,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Redact only fixed payment-card fields and verify no raw card text remains."""

        clean_ticket_id = _required_id(ticket_id, "ticket_id")
        clean_hash = _required_preview_hash(preview_hash)
        clean_key = _required_idempotency_key(idempotency_key)
        operation = "payment_card_ticket_redaction"
        prior = self._prior_salesforce_operation(clean_key)
        if prior is not None:
            if any(
                prior.get(field) != expected
                for field, expected in (
                    ("operation", operation),
                    ("target", clean_ticket_id),
                    ("planHash", clean_hash),
                )
            ):
                raise SalesforceScopeError(
                    "idempotency_key was already used for a different Salesforce operation"
                )
            evidence = prior.get("evidence")
            if prior.get("status") != "accepted" or not isinstance(evidence, dict):
                raise SalesforceScopeError(
                    "payment-card redaction has an uncertain prior outcome; read the ticket before retrying"
                )
            return {
                **dict(evidence),
                "duplicate": True,
                "updated": False,
                "idempotencyKey": clean_key,
            }

        plan, payload = self._payment_card_ticket_redaction_plan(clean_ticket_id)
        if _stable_plan_hash(plan) != clean_hash:
            raise SalesforceScopeError(
                "preview_hash does not match the current ticket payment-card redaction plan"
            )
        if not plan["redactionRequired"]:
            return {
                "ok": True,
                "status": "completed",
                **plan,
                "planHash": clean_hash,
                "updated": False,
                "duplicate": True,
                "verified": True,
                "idempotencyKey": clean_key,
                "readback": {
                    "paymentCardFieldsCleared": True,
                    "rawCardTextAbsent": True,
                },
            }
        with self._salesforce_operation(
            clean_key,
            operation,
            clean_ticket_id,
            clean_hash,
        ) as prior_result:
            if prior_result is not None:
                return {
                    **prior_result,
                    "duplicate": True,
                    "updated": False,
                    "idempotencyKey": clean_key,
                }
            self._request(
                "PATCH",
                f"/sobjects/NovaPOS_Ticket__c/{clean_ticket_id}",
                json=payload,
            )
            readback_plan, _readback_payload = self._payment_card_ticket_redaction_plan(
                clean_ticket_id
            )
            uncleared_fields = list(readback_plan["fieldsToClear"])
            text_fields_remaining = list(readback_plan["textFieldsToRedact"])
            if uncleared_fields or text_fields_remaining:
                raise SalesforceUnavailableError(
                    "Salesforce payment-card redaction readback did not verify; do not retry until the ticket is read again"
                )
            result = {
                "ok": True,
                "status": "completed",
                **plan,
                "planHash": clean_hash,
                "updated": True,
                "duplicate": False,
                "verified": True,
                "idempotencyKey": clean_key,
                "readback": {
                    "paymentCardFieldsCleared": True,
                    "rawCardTextAbsent": True,
                },
            }
            self._complete_salesforce_operation(
                clean_key,
                operation,
                clean_ticket_id,
                clean_hash,
                result,
            )
            return result

    def _payment_card_ticket_redaction_plan(
        self,
        ticket_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        clean_ticket_id = _required_id(ticket_id, "ticket_id")
        self._assert_ticket_scope(clean_ticket_id, {"3. Billing"})
        selected_fields = ",".join(
            (
                "Id",
                "Name",
                "LastModifiedDate",
                *PAYMENT_CARD_TICKET_VALUE_FIELDS,
                *PAYMENT_CARD_TICKET_TEXT_FIELDS,
            )
        )
        query = self._query(
            f"SELECT {selected_fields} FROM NovaPOS_Ticket__c "
            f"WHERE Id = '{clean_ticket_id}' LIMIT 1"
        )
        records = [
            record for record in query.get("records", []) if isinstance(record, dict)
        ]
        if len(records) != 1:
            raise SalesforceScopeError(
                "ticket_id did not resolve to exactly one Salesforce Billing ticket"
            )
        record = records[0]
        fields_to_clear = [
            field
            for field in PAYMENT_CARD_TICKET_VALUE_FIELDS
            if record.get(field) not in {None, ""}
        ]
        payload: dict[str, Any] = {field: None for field in fields_to_clear}
        text_fields_to_redact: list[str] = []
        for field in PAYMENT_CARD_TICKET_TEXT_FIELDS:
            current = str(record.get(field) or "")
            redacted = _redact_ticket_payment_card_text(current)
            if redacted != current:
                payload[field] = redacted
                text_fields_to_redact.append(field)
        plan = {
            "operation": "salesforce_payment_card_ticket_redaction",
            "ticketId": clean_ticket_id,
            "ticketNumber": str(record.get("Name") or "").strip(),
            "sourceLastModifiedDate": str(record.get("LastModifiedDate") or ""),
            "fieldsToClear": sorted(fields_to_clear),
            "textFieldsToRedact": sorted(text_fields_to_redact),
            "redactionRequired": bool(payload),
            "rawPaymentDetailsAccepted": False,
        }
        return plan, payload

    def post_ticket_chatter(
        self,
        ticket_id: str,
        body: str,
        *,
        allowed_record_types: Collection[str] | None = None,
    ) -> dict[str, Any]:
        """Post one timestamped ticket note to Chatter with duplicate precheck and readback."""

        clean_id = _required_id(ticket_id, "ticket_id")
        self._assert_ticket_scope(clean_id, allowed_record_types)
        clean_body = _ticket_chatter_body(body)
        before = self.read_ticket_feed(clean_id, limit=20)
        existing = _matching_ticket_feed_entry(before.get("elements", []), clean_body)
        if existing:
            return {
                "ok": True,
                "posted": False,
                "duplicate": True,
                "verified": True,
                "ticketId": clean_id,
                "feedElement": _bounded_record(existing),
            }

        payload = {
            "body": {"messageSegments": [{"type": "Text", "text": clean_body}]},
            "feedElementType": "FeedItem",
            "subjectId": clean_id,
        }
        result = self._request("POST", "/chatter/feed-elements", json=payload)
        readback: dict[str, Any] | None = None
        for attempt in range(4):
            after = self.read_ticket_feed(clean_id, limit=20)
            readback = _matching_feed_element(after.get("elements", []), clean_body)
            if readback:
                break
            if attempt < 3:
                time.sleep(0.5)
        if not readback:
            raise SalesforceUnavailableError(
                "Salesforce accepted the Chatter post but feed readback was not found; do not retry"
            )
        return {
            "ok": True,
            "posted": True,
            "duplicate": False,
            "verified": True,
            "ticketId": clean_id,
            "feedElement": _bounded_record(readback),
            "providerResult": _bounded_record(result),
        }

    def reply_ticket_chatter(
        self,
        ticket_id: str,
        feed_element_id: str,
        body: str,
        *,
        allowed_record_types: Collection[str] | None = None,
    ) -> dict[str, Any]:
        """Reply once to a verified post on the ticket and read the comment back."""

        clean_id = _required_id(ticket_id, "ticket_id")
        clean_feed_element_id = _required_id(feed_element_id, "feed_element_id")
        self._assert_ticket_scope(clean_id, allowed_record_types)
        clean_body = _ticket_chatter_body(body)
        before = self.read_ticket_feed(clean_id, limit=20)
        elements = before.get("elements", [])
        parent = _feed_element_by_id(elements, clean_feed_element_id)
        if not parent:
            raise SalesforceScopeError(
                "Chatter reply parent was not found on the specified ticket; refresh the ticket feed"
            )
        existing = _matching_ticket_feed_entry(elements, clean_body)
        if existing:
            return {
                "ok": True,
                "posted": False,
                "duplicate": True,
                "verified": True,
                "ticketId": clean_id,
                "parentFeedElementId": clean_feed_element_id,
                "feedEntry": _bounded_record(existing),
            }

        payload = {
            "body": {"messageSegments": [{"type": "Text", "text": clean_body}]},
        }
        result = self._request(
            "POST",
            f"/chatter/feed-elements/{clean_feed_element_id}/capabilities/comments/items",
            json=payload,
        )
        readback: dict[str, Any] | None = None
        for attempt in range(4):
            after = self.read_ticket_feed(clean_id, limit=20)
            readback = _matching_feed_comment(
                after.get("elements", []),
                clean_body,
                parent_feed_element_id=clean_feed_element_id,
            )
            if readback:
                break
            if attempt < 3:
                time.sleep(0.5)
        if not readback:
            raise SalesforceUnavailableError(
                "Salesforce accepted the Chatter reply but comment readback was not found; do not retry"
            )
        return {
            "ok": True,
            "posted": True,
            "duplicate": False,
            "verified": True,
            "ticketId": clean_id,
            "parentFeedElementId": clean_feed_element_id,
            "comment": _bounded_record(readback),
            "providerResult": _bounded_record(result),
        }

    def post_ticket_internal_request(
        self,
        ticket_id: str,
        exact_user: str,
        message: str,
        idempotency_key: str,
        *,
        allowed_record_types: Collection[str] | None = None,
    ) -> dict[str, Any]:
        """Post one concise internal request with a verified Salesforce user mention."""

        clean_id = _required_id(ticket_id, "ticket_id")
        self._assert_ticket_scope(clean_id, allowed_record_types)
        recipient = self._resolve_internal_salesforce_user(exact_user)
        clean_message = _ticket_internal_request_body(message, recipient)
        recipient_id = str(recipient["Id"])
        recipient_name = str(recipient["Name"])
        clean_key = _required_idempotency_key(idempotency_key)
        operation = "salesforce_ticket_internal_request_post"
        target = f"{clean_id}:{recipient_id}"
        plan_hash = _stable_plan_hash(
            {
                "ticketId": clean_id,
                "recipientId": recipient_id,
                "message": clean_message,
            }
        )

        def verified_feed_element() -> dict[str, Any] | None:
            feed = self.read_ticket_feed(clean_id, limit=20)
            return _matching_mentioned_feed_element(
                feed.get("elements", []),
                recipient_id=recipient_id,
                message=clean_message,
            )

        def recovered_evidence() -> dict[str, Any] | None:
            feed_element = verified_feed_element()
            if not feed_element:
                return None
            return {
                "ok": True,
                "posted": False,
                "duplicate": True,
                "verified": True,
                "ticketId": clean_id,
                "recipient": {
                    "name": recipient_name,
                    "tagged": True,
                },
                "feedElement": _bounded_record(feed_element),
                "idempotencyKey": clean_key,
            }

        with self._salesforce_operation(
            clean_key,
            operation,
            target,
            plan_hash,
            track_provider_attempt=True,
            reconcile_pending=recovered_evidence,
        ) as prior:
            if prior is not None:
                evidence = {
                    **prior,
                    "ok": True,
                    "posted": False,
                    "duplicate": True,
                    "verified": True,
                    "replayed": True,
                    "writesPerformed": False,
                    "idempotencyKey": clean_key,
                }
                restore_verified_internal_request_day(
                    recipient_id,
                    verified_local_date=str(
                        evidence.get("internalRequestLocalDate") or ""
                    ),
                    channel="salesforce",
                    provider_id=str(
                        (
                            evidence.get("feedElement")
                            if isinstance(evidence.get("feedElement"), dict)
                            else {}
                        ).get("id")
                        or ""
                    ),
                    journal_path=self._internal_communication_journal_path,
                )
                return evidence

            with internal_request_day(
                recipient_id,
                journal_path=self._internal_communication_journal_path,
            ) as communication:
                segments: list[dict[str, str]] = []
                if communication.greeting_required:
                    segments.append({"type": "Text", "text": "Hey "})
                segments.append({"type": "Mention", "id": recipient_id})
                segments.append(
                    {
                        "type": "Text",
                        "text": (
                            ", " if communication.greeting_required else " "
                        )
                        + clean_message,
                    }
                )

                existing = verified_feed_element()
                if existing:
                    evidence = {
                        "ok": True,
                        "posted": False,
                        "duplicate": True,
                        "verified": True,
                        "replayed": False,
                        "writesPerformed": False,
                        "ticketId": clean_id,
                        "recipient": {
                            "name": recipient_name,
                            "tagged": True,
                        },
                        "firstMessageGreetingIncluded": bool(
                            communication.greeting_required
                        ),
                        "feedElement": _bounded_record(existing),
                        "idempotencyKey": clean_key,
                    }
                    self._complete_salesforce_operation(
                        clean_key,
                        operation,
                        target,
                        plan_hash,
                        evidence,
                    )
                    return evidence

                payload = {
                    "body": {"messageSegments": segments},
                    "feedElementType": "FeedItem",
                    "subjectId": clean_id,
                }
                self._mark_salesforce_provider_attempt(
                    clean_key,
                    operation,
                    target,
                    plan_hash,
                    evidence={
                        "internalRequestLocalDate": communication.local_date,
                        "firstMessageGreetingIncluded": bool(
                            communication.greeting_required
                        ),
                    },
                )
                result = self._request("POST", "/chatter/feed-elements", json=payload)
                readback: dict[str, Any] | None = None
                for attempt in range(4):
                    readback = verified_feed_element()
                    if readback:
                        break
                    if attempt < 3:
                        time.sleep(0.5)
                if not readback:
                    raise SalesforceUnavailableError(
                        "Salesforce accepted the tagged Chatter request but mention readback "
                        "was not found; do not retry"
                    )
                evidence = {
                    "ok": True,
                    "posted": True,
                    "duplicate": False,
                    "verified": True,
                    "replayed": False,
                    "writesPerformed": True,
                    "ticketId": clean_id,
                    "recipient": {
                        "name": recipient_name,
                        "tagged": True,
                    },
                    "firstMessageGreetingIncluded": bool(
                        communication.greeting_required
                    ),
                    "internalRequestLocalDate": communication.local_date,
                    "feedElement": _bounded_record(readback),
                    "providerResult": _bounded_record(result),
                    "idempotencyKey": clean_key,
                }
                communication.record_verified(
                    channel="salesforce",
                    provider_id=str(readback.get("id") or ""),
                )
                self._complete_salesforce_operation(
                    clean_key,
                    operation,
                    target,
                    plan_hash,
                    evidence,
                )
                return evidence

    def _resolve_internal_salesforce_user(self, exact_user: str) -> dict[str, Any]:
        """Resolve one active Nova employee without exposing a directory listing."""

        requested = " ".join(str(exact_user or "").split())
        if not 2 <= len(requested) <= 254:
            raise SalesforceScopeError(
                "exact_user must be one exact Nova employee email, full name, or unique first name"
            )
        requested_email = requested.casefold() if "@" in requested else ""
        if requested_email:
            if not EMAIL.fullmatch(requested):
                raise SalesforceScopeError("exact_user email is invalid")
            predicate = f"Email = '{_escape_soql(requested)}'"
        elif " " in requested:
            predicate = f"Name = '{_escape_soql(requested)}'"
        else:
            predicate = f"FirstName = '{_escape_soql(requested)}'"

        result = self._query(
            "SELECT Id,Name,FirstName,LastName,Email,IsActive "
            f"FROM User WHERE IsActive = TRUE AND {predicate} LIMIT 3"
        )
        matches: list[dict[str, Any]] = []
        for record in result.get("records", []):
            if not isinstance(record, dict) or record.get("IsActive") is not True:
                continue
            user_id = str(record.get("Id") or "").strip()
            email = str(record.get("Email") or "").strip()
            name = " ".join(str(record.get("Name") or "").split())
            first_name = " ".join(str(record.get("FirstName") or "").split())
            if not re.fullmatch(r"005[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?", user_id):
                continue
            if not _is_nova_internal_email(email):
                continue
            if requested_email:
                exact_match = email.casefold() == requested_email
            elif " " in requested:
                exact_match = _normalized_text(name) == _normalized_text(requested)
            else:
                exact_match = _normalized_text(first_name) == _normalized_text(requested)
            if exact_match:
                matches.append(
                    {
                        "Id": user_id,
                        "Name": name,
                        "FirstName": first_name or name.split(" ", 1)[0],
                        "Email": email,
                    }
                )
        if len(matches) != 1:
            raise SalesforceScopeError(
                "exact_user did not resolve to exactly one active Nova Salesforce user"
            )
        return matches[0]

    def update_ticket_internal_note(
        self,
        ticket_id: str,
        note: str,
        *,
        allowed_record_types: Collection[str] | None = None,
    ) -> dict[str, Any]:
        """Legacy alias that now posts to Chatter instead of Technical Notes."""

        result = self.post_ticket_chatter(
            ticket_id,
            note,
            allowed_record_types=allowed_record_types,
        )
        return {**result, "legacyAlias": True, "field": "Chatter"}

    def resolve_ticket(
        self,
        ticket_id: str,
        resolution_note: str,
        *,
        reply_to_feed_element_id: str = "",
        allowed_record_types: Collection[str] | None = None,
    ) -> dict[str, Any]:
        """Close with complete metadata, adding Chatter only for a supplied net-new result."""

        clean_id = _required_id(ticket_id, "ticket_id")
        self._assert_ticket_scope(clean_id, allowed_record_types)
        raw_note = str(resolution_note or "").strip()
        clean_note = _bounded(raw_note, "resolution_note", 5_000) if raw_note else ""
        clean_reply_to = (
            _required_id(reply_to_feed_element_id, "reply_to_feed_element_id")
            if str(reply_to_feed_element_id or "").strip()
            else ""
        )
        if clean_note and clean_reply_to:
            feed = self.read_ticket_feed(clean_id, limit=20)
            if not _feed_element_by_id(feed.get("elements", []), clean_reply_to):
                raise SalesforceScopeError(
                    "Chatter reply parent was not found on the specified ticket; refresh the ticket feed"
                )
        before = self.read_ticket(clean_id)["record"]
        already_closed = before.get("Is_Closed__c") is True
        if not already_closed:
            closed_by_rep = self._resolve_ticket_closed_by_rep(
                clean_id,
                before.get(TICKET_CLOSED_BY_REP_FIELD),
            )
            payload = {
                "Is_Closed__c": True,
                "Ticket_Closed_Date__c": datetime.now(timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
                TICKET_CLOSED_BY_REP_FIELD: closed_by_rep,
            }
            self._request("PATCH", f"/sobjects/NovaPOS_Ticket__c/{clean_id}", json=payload)
            closure_readback = self._ticket_closure_metadata(clean_id)
            if (
                closure_readback.get("Is_Closed__c") is not True
                or not str(closure_readback.get("Ticket_Closed_Date__c") or "").strip()
                or str(closure_readback.get(TICKET_CLOSED_BY_REP_FIELD) or "").strip()
                != closed_by_rep
            ):
                raise SalesforceUnavailableError(
                    "Salesforce ticket closure metadata readback did not match; "
                    "read the ticket before any retry"
                )
        else:
            closure_readback = self._ticket_closure_metadata(clean_id)
            if closure_readback.get("Is_Closed__c") is not True:
                raise SalesforceUnavailableError(
                    "Salesforce ticket closed-status readback did not match; read the ticket before any retry"
                )

        if clean_note and clean_reply_to:
            chatter = self.reply_ticket_chatter(
                clean_id,
                clean_reply_to,
                clean_note,
                allowed_record_types=allowed_record_types,
            )
        elif clean_note:
            chatter = self.post_ticket_chatter(
                clean_id,
                clean_note,
                allowed_record_types=allowed_record_types,
            )
        else:
            chatter = {
                "ok": True,
                "posted": False,
                "duplicate": False,
                "verified": True,
                "omitted": True,
                "reason": "no net-new ticket update supplied",
                "ticketId": clean_id,
            }
        readback = {
            **self.read_ticket(clean_id)["record"],
            **closure_readback,
        }
        verified_closed = readback.get("Is_Closed__c") is True
        if not chatter.get("verified") or not verified_closed:
            raise SalesforceUnavailableError(
                "Salesforce ticket resolve readback did not verify the resolution and closed status; do not retry"
            )
        updated = not already_closed or bool(chatter.get("posted"))
        return {
            "ok": True,
            "updated": updated,
            "duplicate": not updated,
            "id": clean_id,
            "closed": True,
            "resolutionPresent": bool(clean_note),
            "resolutionSurface": (
                "ChatterReply" if clean_note and clean_reply_to else "Chatter" if clean_note else "None"
            ),
            "chatter": chatter,
            "closureReadback": closure_readback,
            "readback": readback,
        }

    def create_order(self, fields: dict[str, Any]) -> dict[str, Any]:
        payload = _allowlisted_fields(fields, ORDER_CREATE_FIELDS, "order")
        if "Account__c" not in payload:
            raise SalesforceScopeError("Order Account__c is required")
        if _normalized_picklist_text(payload.get("Existing_Order_Type__c")) == _normalized_picklist_text(
            FORBIDDEN_AGENT_ORDER_TYPE_LABEL
        ):
            raise SalesforceScopeError(
                "New Customer Order is reserved for the website's first order on a new Account; "
                "agent order creation is prohibited"
            )
        cancellation_markers = (
            "Reason_for_cancellation__c" in payload
            or "Cancellation_Order_Notes__c" in payload
            or (
                _integer_identifier(
                    payload.get("Total_Number_of_Locations_for_this_order__c")
                )
                or 0
            )
            < 0
            or "cancellation"
            in _normalized_picklist_text(payload.get("Existing_Order_Type__c"))
        )
        if cancellation_markers:
            raise SalesforceScopeError(
                "Cancellation orders must use the typed account- or location-cancellation "
                "preview/apply operation so every closed location is grouped into one "
                "subscription-linked order"
            )
        payload["Account__c"] = _required_id(str(payload["Account__c"]), "Account__c")
        if "RecordTypeId" in payload:
            payload["RecordTypeId"] = _required_id(str(payload["RecordTypeId"]), "RecordTypeId")
        created = self._request("POST", "/sobjects/NovaPOS_Order__c", json=payload)
        record_id = _required_id(str(created.get("id") or ""), "created order id")
        readback = self.lookup("order", record_id, limit=1)
        return {"ok": True, "created": True, "id": record_id, "readback": readback["records"]}

    def update_location(self, location_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        clean_id = _required_id(location_id, "location_id")
        payload = _allowlisted_fields(fields, LOCATION_UPDATE_FIELDS, "location")
        self._request("PATCH", f"/sobjects/NovaPOS_Location__c/{clean_id}", json=payload)
        readback = self.lookup("location", clean_id, limit=1)
        return {"ok": True, "updated": True, "id": clean_id, "readback": readback["records"]}

    def update_ticket_contact_email(
        self,
        ticket_id: str,
        contact_id: str,
        email: str,
        *,
        idempotency_key: str,
        allowed_record_types: Collection[str] | None = None,
    ) -> dict[str, Any]:
        """Update only the linked ticket Contact email and verify exact readback."""

        clean_ticket_id = _required_id(ticket_id, "ticket_id")
        clean_contact_id = _required_id(contact_id, "contact_id")
        clean_key = _required_idempotency_key(idempotency_key)
        clean_email = str(email or "").strip()
        if len(clean_email) > 254 or not EMAIL.fullmatch(clean_email):
            raise SalesforceScopeError("email must be one valid address")
        self._assert_ticket_scope(clean_ticket_id, allowed_record_types)
        ticket = self.read_ticket(clean_ticket_id)["record"]
        if str(ticket.get("Contact__c") or "") != clean_contact_id:
            raise SalesforceScopeError(
                "contact_id must already be the Contact linked to this ticket; "
                "use the scoped ticket update first when a different verified Contact is required"
            )
        contact = self._request("GET", f"/sobjects/Contact/{clean_contact_id}")
        ticket_account = str(ticket.get("Account__c") or "")
        if not ticket_account or str(contact.get("AccountId") or "") != ticket_account:
            raise SalesforceScopeError("ticket Contact does not belong to the ticket Account")
        before_email = str(contact.get("Email") or "").strip()
        if before_email.casefold() == clean_email.casefold():
            return {
                "ok": True,
                "updated": False,
                "duplicate": True,
                "verified": True,
                "ticketId": clean_ticket_id,
                "contactId": clean_contact_id,
                "email": clean_email,
                "idempotencyKey": clean_key,
            }
        self._request(
            "PATCH",
            f"/sobjects/Contact/{clean_contact_id}",
            json={"Email": clean_email},
        )
        readback = self._request("GET", f"/sobjects/Contact/{clean_contact_id}")
        if str(readback.get("Email") or "").strip().casefold() != clean_email.casefold():
            raise SalesforceUnavailableError(
                "Salesforce Contact email readback did not match; do not retry until the Contact is read again"
            )
        return {
            "ok": True,
            "updated": True,
            "duplicate": False,
            "verified": True,
            "ticketId": clean_ticket_id,
            "contactId": clean_contact_id,
            "email": clean_email,
            "beforeEmail": before_email,
            "idempotencyKey": clean_key,
            "readback": _bounded_record(readback),
        }

    def update_cancellation_order_reason(
        self,
        order_id: str,
        reason: str,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Update only the cancellation reason on one existing Cancellation Order and verify exact readback."""

        clean_order_id = _required_id(order_id, "order_id")
        clean_key = _required_idempotency_key(idempotency_key)
        clean_reason = str(reason or "").strip()
        if not clean_reason:
            raise SalesforceScopeError("reason is required")
        order = self._request("GET", f"/sobjects/NovaPOS_Order__c/{clean_order_id}")
        if str(order.get("Order_Type_Formula__c") or "") != CANCELLATION_ORDER_FORMULA_LABEL:
            raise SalesforceScopeError(
                "order_id is not an existing Cancellation Order; the cancellation reason may only be "
                "corrected on a closing order"
            )
        account_id = str(order.get("Account__c") or "")
        if not account_id:
            raise SalesforceScopeError("Cancellation Order is missing its Account link")
        cancellation_record_type = self._resolve_cancellation_order_record_type()
        if str(order.get("RecordTypeId") or "") != str(cancellation_record_type["Id"]):
            raise SalesforceScopeError(
                "order_id is not an Existing Customer Cancellation Order record type"
            )
        reason_value = self._resolve_order_picklist_value(
            str(order.get("RecordTypeId") or ""),
            "Reason_for_cancellation__c",
            clean_reason,
        )
        before_reason = str(order.get("Reason_for_cancellation__c") or "")
        if before_reason == reason_value:
            return {
                "ok": True,
                "updated": False,
                "duplicate": True,
                "verified": True,
                "orderId": clean_order_id,
                "accountId": account_id,
                "reason": reason_value,
                "idempotencyKey": clean_key,
            }
        self._request(
            "PATCH",
            f"/sobjects/NovaPOS_Order__c/{clean_order_id}",
            json={"Reason_for_cancellation__c": reason_value},
        )
        readback = self._request("GET", f"/sobjects/NovaPOS_Order__c/{clean_order_id}")
        if str(readback.get("Reason_for_cancellation__c") or "") != reason_value:
            raise SalesforceUnavailableError(
                "Salesforce cancellation order reason readback did not match; "
                "do not retry until the Cancellation Order is read again"
            )
        if str(readback.get("Id") or "") != clean_order_id:
            raise SalesforceUnavailableError(
                "Salesforce returned a different Cancellation Order on readback; "
                "do not retry until the order is read again"
            )
        return {
            "ok": True,
            "updated": True,
            "duplicate": False,
            "verified": True,
            "orderId": clean_order_id,
            "accountId": account_id,
            "beforeReason": before_reason,
            "reason": reason_value,
            "idempotencyKey": clean_key,
            "readback": _bounded_record(readback),
        }

    def update_email_template_html(
        self,
        template_id: str,
        html_value: str,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Replace the HTML body of one curated EmailTemplate and verify exact readback."""

        clean_template_id = _required_id(template_id, "template_id")
        clean_key = _required_idempotency_key(idempotency_key)
        clean_html = str(html_value or "").strip()
        if not clean_html:
            raise SalesforceScopeError("html_value is required")
        if len(clean_html) > 40000:
            raise SalesforceScopeError("html_value exceeds the 40,000 character limit")
        record = self._request("GET", f"/sobjects/EmailTemplate/{clean_template_id}")
        identity = (
            str(record.get("FolderId") or "")[:15],
            str(record.get("DeveloperName") or ""),
        )
        spec = EMAIL_TEMPLATE_REGISTRY.get(identity)
        if not spec or str(spec.get("expectedTemplateId") or "") != clean_template_id:
            raise SalesforceScopeError(
                "template_id is not the exact curated template for its approved folder and developer name"
            )
        subject_before = str(record.get("Subject") or "")
        name_before = str(record.get("Name") or "")
        html_before = str(record.get("HtmlValue") or "")
        if html_before == clean_html:
            return {
                "ok": True,
                "updated": False,
                "duplicate": True,
                "verified": True,
                "templateId": clean_template_id,
                "templateName": name_before,
                "situation": str(spec.get("situation") or ""),
                "idempotencyKey": clean_key,
            }
        text = _normalized_email_body(
            re.sub(r"<[^>]+>", " ", clean_html).replace(" ", " ")
        )
        for fragment in spec.get("requiredBodyFragments") or ():
            normalized = _normalized_text(fragment)
            if normalized and normalized not in text:
                raise SalesforceScopeError(
                    f"html_value dropped required approved content: {fragment}"
                )
        for marker in ("{!", "{{", "}}"):
            if marker in clean_html:
                raise SalesforceScopeError(
                    "html_value contains an unresolved template marker"
                )
        placeholder = None
        pos = clean_html.find("[")
        while pos >= 0:
            close = clean_html.find("]", pos + 1)
            if close < 0:
                break
            inner = clean_html[pos + 1 : close]
            if len(inner) >= 2 and "\r" not in inner and "\n" not in inner:
                placeholder = inner
                break
            pos = clean_html.find("[", pos + 1)
        if placeholder is not None:
            raise SalesforceScopeError(
                "html_value contains an unresolved manual placeholder"
            )
            raise SalesforceScopeError(
                "html_value contains an unresolved manual placeholder"
            )
        if re.search(r"javascript:", clean_html, re.I):
            raise SalesforceScopeError("html_value may not contain javascript: links")
        old_links = sorted(
            match.group(1).casefold()
            for match in re.finditer(r'href="([^"]+)"', html_before)
        )
        new_links = sorted(
            match.group(1).casefold()
            for match in re.finditer(r"href=[\"']([^\"']+)[\"']", clean_html)
        )
        if not set(old_links).issubset(set(new_links)):
            raise SalesforceScopeError(
                "html_value removed a link the approved template already carried"
            )
        self._request(
            "PATCH",
            f"/sobjects/EmailTemplate/{clean_template_id}",
            json={"HtmlValue": clean_html},
        )
        readback = self._request("GET", f"/sobjects/EmailTemplate/{clean_template_id}")
        if str(readback.get("HtmlValue") or "") != clean_html:
            raise SalesforceUnavailableError(
                "Salesforce email template HTML readback did not match; "
                "do not retry until the template is read again"
            )
        if (
            str(readback.get("Id") or "") != clean_template_id
            or str(readback.get("Subject") or "") != subject_before
            or str(readback.get("Name") or "") != name_before
            or str(readback.get("DeveloperName") or "") != identity[1]
        ):
            raise SalesforceUnavailableError(
                "Salesforce returned a different email template identity on readback; "
                "do not retry until the template is read again"
            )
        return {
            "ok": True,
            "updated": True,
            "duplicate": False,
            "verified": True,
            "templateId": clean_template_id,
            "templateName": name_before,
            "subject": subject_before,
            "situation": str(spec.get("situation") or ""),
            "beforeSha256": hashlib.sha256(html_before.encode("utf-8")).hexdigest(),
            "afterSha256": hashlib.sha256(clean_html.encode("utf-8")).hexdigest(),
            "idempotencyKey": clean_key,
        }

    def read_account_locations(self, account_id: str, *, limit: int = 500) -> dict[str, Any]:
        """Read the Salesforce locations used by Rainfall lifecycle and rate workflows."""

        clean_id = _required_id(account_id, "account_id")
        clean_limit = max(1, min(int(limit), 500))
        result = self._query(
            "SELECT Id,Name,Account__c,Location_ID__c,Status__c,Bill_Amount__c,"
            "Chargify_Subscription_ID__c,NovaPOS_Billing_Schedule__c,"
            "Is_Location_on_GSPayTech_Gateway__c "
            f"FROM NovaPOS_Location__c WHERE Account__c = '{clean_id}' "
            f"ORDER BY Location_ID__c,Id LIMIT {clean_limit}"
        )
        records = [_bounded_record(record) for record in result.get("records", []) if isinstance(record, dict)]
        return {"ok": True, "accountId": clean_id, "records": records, "count": len(records)}

    def read_account_orders(self, account_id: str, *, limit: int = 100) -> dict[str, Any]:
        """Read bounded order and approval evidence for one exact Account."""

        clean_id = _required_id(account_id, "account_id")
        clean_limit = max(1, min(int(limit), 100))
        result = self._query(
            "SELECT Id,Name,Account__c,RecordTypeId,Contract_Name__c,Description__c,"
            "Existing_Order_Type__c,"
            "Reason_for_cancellation__c,Location_I_D__c,Chargify_Subscription_ID__c,"
            "Total_Number_of_Locations_for_this_order__c,Billing_Start_Date1__c,CreatedDate "
            f"FROM NovaPOS_Order__c WHERE Account__c = '{clean_id}' "
            f"ORDER BY CreatedDate DESC LIMIT {clean_limit}"
        )
        records = [
            dict(_bounded_record(raw))
            for raw in result.get("records", [])
            if isinstance(raw, dict)
        ]
        approvals = self._order_approval_states(
            [str(record.get("Id") or "") for record in records]
        )
        for record in records:
            record["approval"] = approvals.get(
                str(record.get("Id") or ""),
                {"submitted": False, "status": "", "records": []},
            )
        return {"ok": True, "accountId": clean_id, "records": records, "count": len(records)}

    def _resolve_location_lifecycle_order_record_type(self, classification: str) -> dict[str, Any]:
        aliases = {
            _normalized_picklist_text(alias)
            for alias in LOCATION_LIFECYCLE_ORDER_RECORD_TYPE_ALIASES[classification]
        }
        result = self._query(
            "SELECT Id,Name,DeveloperName FROM RecordType "
            "WHERE SobjectType = 'NovaPOS_Order__c' AND IsActive = true LIMIT 100"
        )
        matches = [
            dict(record)
            for record in result.get("records", [])
            if isinstance(record, dict)
            and aliases.intersection(
                {
                    _normalized_picklist_text(record.get("Name")),
                    _normalized_picklist_text(record.get("DeveloperName")),
                }
            )
        ]
        if len(matches) != 1:
            raise SalesforceScopeError(
                f"Salesforce {classification} order RecordType did not resolve to exactly one active record type"
            )
        matches[0].pop("attributes", None)
        return matches[0]

    def _resolve_location_lifecycle_order_type(
        self,
        record_type_id: str,
        classification: str,
        action: str,
    ) -> str:
        if classification == "within_3_months":
            candidates = (LOCATION_LIFECYCLE_ACTION_TYPE_LABELS[action],)
        else:
            candidates = (
                LOCATION_LIFECYCLE_ORDER_TYPE_LABELS[classification],
                *LOCATION_LIFECYCLE_ORDER_RECORD_TYPE_ALIASES[classification],
            )
        last_error: SalesforceScopeError | None = None
        for candidate in candidates:
            try:
                resolved = self._resolve_order_picklist_value(
                    record_type_id,
                    "Existing_Order_Type__c",
                    candidate,
                )
            except SalesforceScopeError as exc:
                last_error = exc
                continue
            if _normalized_picklist_text(resolved) == _normalized_picklist_text(
                FORBIDDEN_AGENT_ORDER_TYPE_LABEL
            ):
                raise SalesforceScopeError(
                    "New Customer Order is reserved for the website's first order on a new Account"
                )
            return str(resolved)
        raise last_error or SalesforceScopeError(
            "Existing_Order_Type__c did not resolve for the requested lifecycle order"
        )

    def location_lifecycle_order_preview(
        self,
        ticket_id: str,
        account_id: str,
        salesforce_location_ids: list[str],
        action: str,
        chargify_subscription_id: int,
        *,
        monthly_rate_cents: int = 9_999,
        merchant_provider: str = "",
    ) -> dict[str, Any]:
        """Preview one no-approval reactivation or additional-location order."""

        clean_ticket_id = _required_id(ticket_id, "ticket_id")
        clean_account_id = _required_id(account_id, "account_id")
        clean_action = str(action or "").strip().casefold()
        if clean_action not in LOCATION_LIFECYCLE_ORDER_ACTIONS:
            raise SalesforceScopeError(
                "action must be reactivate_existing_location or add_additional_location"
            )
        clean_subscription_id = _positive_salesforce_external_id(
            chargify_subscription_id,
            "chargify_subscription_id",
        )
        selected_ids = sorted(
            {_required_id(value, "salesforce_location_id") for value in salesforce_location_ids}
        )
        if not selected_ids:
            raise SalesforceScopeError("at least one exact Salesforce location is required")

        ticket = self._assert_operational_ticket_account(
            clean_ticket_id,
            clean_account_id,
        )

        account_result = self._query(
            "SELECT Id,Name,CreatedDate,OwnerId,"
            "Nova_Account_Manager__c,Flat_Rate_Amount__c "
            f"FROM Account WHERE Id = '{clean_account_id}' LIMIT 1"
        )
        account_rows = [
            dict(row)
            for row in account_result.get("records", [])
            if isinstance(row, dict)
        ]
        if len(account_rows) != 1:
            raise SalesforceScopeError("account_id did not resolve to exactly one Salesforce Account")
        account = account_rows[0]
        eligibility_date_field = "CreatedDate"
        eligibility_started_at = _salesforce_datetime(
            account.get(eligibility_date_field),
            f"Account.{eligibility_date_field}",
        )
        eligibility_cutoff_at = _three_calendar_month_boundary(eligibility_started_at)
        within_three_months = (
            clean_action == "add_additional_location"
            and _within_first_three_calendar_months(
                eligibility_started_at,
                datetime.now(timezone.utc),
            )
        )

        quoted = ",".join(f"'{value}'" for value in selected_ids)
        location_result = self._query(
            "SELECT Id,Name,Account__c,Location_ID__c,Status__c,Bill_Amount__c,"
            "Chargify_Subscription_ID__c,NovaPOS_Billing_Schedule__c,"
            "Is_Location_on_GSPayTech_Gateway__c "
            f"FROM NovaPOS_Location__c WHERE Id IN ({quoted}) LIMIT {len(selected_ids)}"
        )
        locations = [
            dict(row)
            for row in location_result.get("records", [])
            if isinstance(row, dict)
        ]
        if {str(row.get("Id") or "") for row in locations} != set(selected_ids):
            raise SalesforceScopeError("salesforce_location_ids did not resolve exactly")

        normalized_locations: list[dict[str, Any]] = []
        for location in locations:
            if str(location.get("Account__c") or "") != clean_account_id:
                raise SalesforceScopeError("every selected location must belong to account_id")
            nova_location_id = _normalized_location_id(location.get("Location_ID__c"))
            if not nova_location_id:
                raise SalesforceScopeError("every selected location requires one numeric Location_ID__c")
            if _normalized_text(str(location.get("Status__c") or "")) != "active":
                raise SalesforceScopeError(
                    "create the lifecycle order only after each selected Salesforce location is Active"
                )
            if _numeric_identifier(location.get("Chargify_Subscription_ID__c")) != clean_subscription_id:
                raise SalesforceScopeError(
                    "every selected location must read back the exact Chargify subscription before order creation"
                )
            if not SALESFORCE_ID.fullmatch(str(location.get("NovaPOS_Billing_Schedule__c") or "")):
                raise SalesforceScopeError(
                    "every selected location must read back one Salesforce Billing Schedule before order creation"
                )
            normalized_locations.append(
                {
                    "recordId": str(location["Id"]),
                    "locationId": nova_location_id,
                    "billAmountCents": _decimal_currency_field_to_cents(location.get("Bill_Amount__c")),
                    "integrated": location.get("Is_Location_on_GSPayTech_Gateway__c") is True,
                    "billingScheduleId": str(location["NovaPOS_Billing_Schedule__c"]),
                }
            )

        clean_provider = ""
        clean_rate = _nonnegative_cents(monthly_rate_cents, "monthly_rate_cents")
        if clean_action == "add_additional_location":
            clean_provider = _merchant_provider(merchant_provider)
            if clean_rate <= 0:
                raise SalesforceScopeError("monthly_rate_cents must be positive for a new location")
            for location in normalized_locations:
                if location["billAmountCents"] != clean_rate:
                    raise SalesforceScopeError(
                        "each new location must read back the ticket rate, or 9999 cents by default, "
                        "on NovaPOS_Location__c.Bill_Amount__c"
                    )
                if not location["integrated"]:
                    raise SalesforceScopeError(
                        "each new location must read back as Nova Integrated before order creation"
                    )
        classification = (
            "reactivate_existing_location"
            if clean_action == "reactivate_existing_location"
            else "within_3_months" if within_three_months else "existing_additional"
        )

        record_type = self._resolve_location_lifecycle_order_record_type(classification)
        record_type_id = _required_id(str(record_type.get("Id") or ""), "record type id")
        order_type = self._resolve_location_lifecycle_order_type(
            record_type_id,
            classification,
            clean_action,
        )
        if "new customer" in _normalized_picklist_text(order_type):
            raise SalesforceScopeError(
                "New Customer Order is reserved for the website's first order on a new Account"
            )

        normalized_locations.sort(key=lambda row: int(row["locationId"]))
        location_csv = ",".join(row["locationId"] for row in normalized_locations)
        count = len(normalized_locations)
        owner_id = str(account.get("Nova_Account_Manager__c") or account.get("OwnerId") or "")
        action_text = "Reactivated" if clean_action == "reactivate_existing_location" else "Added"
        order_fields: dict[str, Any] = {
            "Account__c": clean_account_id,
            "RecordTypeId": record_type_id,
            "Contract_Name__c": f"{count} Location{'s' if count != 1 else ''}. Billing Automation Order",
            "Description__c": f"Ticket {ticket.get('Name') or clean_ticket_id}. {action_text} locations {location_csv}.",
            "Existing_Order_Type__c": order_type,
            "Total_Number_of_Locations_for_this_order__c": count,
            "Location_I_D__c": location_csv,
            "Billing_Start_Date1__c": datetime.now(timezone.utc).date().isoformat(),
            "Chargify_Subscription_ID__c": clean_subscription_id,
        }
        if SALESFORCE_ID.fullmatch(owner_id):
            order_fields["Order_Assigned_To_c__c"] = owner_id

        existing = self.read_account_orders(clean_account_id)["records"]
        duplicate_order = next(
            (
                order
                for order in existing
                if self._location_lifecycle_order_readback_matches(
                    order,
                    order_fields,
                    allow_different_billing_date=True,
                )
            ),
            None,
        )
        reclassification_candidates = [
            order
            for order in existing
            if duplicate_order is None
            and self._location_lifecycle_order_business_identity_matches(
                order,
                order_fields,
                allow_different_billing_date=True,
            )
        ]
        if len(reclassification_candidates) > 1:
            raise SalesforceScopeError(
                "multiple lifecycle orders matched the same ticket, subscription, and locations; "
                "do not reclassify or create another order"
            )
        order_to_reclassify = (
            reclassification_candidates[0] if reclassification_candidates else None
        )
        duplicate_approval = (
            duplicate_order.get("approval")
            if isinstance(duplicate_order, dict) and isinstance(duplicate_order.get("approval"), dict)
            else {"submitted": False, "status": "", "records": []}
        )
        if duplicate_approval.get("submitted"):
            raise SalesforceScopeError(
                "the matching lifecycle order already entered approval; do not create a duplicate or submit it again"
            )
        reclassification_approval = (
            order_to_reclassify.get("approval")
            if isinstance(order_to_reclassify, dict)
            and isinstance(order_to_reclassify.get("approval"), dict)
            else {"submitted": False, "status": "", "records": []}
        )
        if reclassification_approval.get("submitted"):
            raise SalesforceScopeError(
                "the lifecycle order needing reclassification already entered approval; "
                "do not update it or create a duplicate"
            )

        plan = {
            "operation": "salesforce_location_lifecycle_order",
            "ticketId": clean_ticket_id,
            "ticketNumber": str(ticket.get("Name") or ""),
            "accountId": clean_account_id,
            "action": clean_action,
            "classification": classification,
            "classificationDateField": eligibility_date_field,
            "classificationStartedAt": eligibility_started_at.isoformat(),
            "classificationCutoffAt": eligibility_cutoff_at.isoformat(),
            "withinFirstThreeCalendarMonths": within_three_months,
            "recordType": _bounded_record(record_type),
            "orderType": order_type,
            "locationRecordIds": selected_ids,
            "locationIds": [row["locationId"] for row in normalized_locations],
            "locationCount": count,
            "chargifySubscriptionId": clean_subscription_id,
            "merchantProvider": clean_provider,
            "monthlyRateCents": clean_rate if clean_action == "add_additional_location" else None,
            "orderFields": order_fields,
            "duplicateOrder": duplicate_order,
            "orderToReclassify": order_to_reclassify,
            "approvalSubmissionIncluded": False,
            "approvalSubmissionProhibited": True,
            "reactivationFromDeclineIncluded": False,
            "locationReactivatedInNovaPOSIncluded": False,
            "accountActivatedInNovaPOSIncluded": False,
            "accountFlatRateMutationIncluded": False,
            "billingStartStopDateField": "Billing_Start_Date1__c",
            "newCustomerOrderAllowed": False,
        }
        return {
            "ok": True,
            "status": (
                "already_created"
                if duplicate_order
                else "reclassification_preview"
                if order_to_reclassify
                else "preview"
            ),
            "verified": True,
            **plan,
            "previewHash": _stable_plan_hash(plan),
            "writesPerformed": False,
            "applyRequired": not bool(duplicate_order),
        }

    def apply_location_lifecycle_order(
        self,
        ticket_id: str,
        account_id: str,
        salesforce_location_ids: list[str],
        action: str,
        chargify_subscription_id: int,
        *,
        preview_hash: str,
        idempotency_key: str,
        monthly_rate_cents: int = 9_999,
        merchant_provider: str = "",
    ) -> dict[str, Any]:
        """Create or reclassify one unchanged lifecycle order and prove no approval was submitted."""

        clean_hash = _required_preview_hash(preview_hash)
        clean_key = _required_idempotency_key(idempotency_key)
        preview = self.location_lifecycle_order_preview(
            ticket_id,
            account_id,
            salesforce_location_ids,
            action,
            chargify_subscription_id,
            monthly_rate_cents=monthly_rate_cents,
            merchant_provider=merchant_provider,
        )
        if preview["previewHash"] != clean_hash:
            raise SalesforceScopeError(
                "preview_hash does not match the current location lifecycle order plan"
            )
        duplicate_order = preview.get("duplicateOrder")
        if isinstance(duplicate_order, dict) and duplicate_order.get("Id"):
            return {
                **preview,
                "status": "already_created",
                "created": False,
                "duplicate": True,
                "verified": True,
                "orderId": str(duplicate_order["Id"]),
                "approvalSubmitted": False,
                "idempotencyKey": clean_key,
            }

        target = f"{preview['accountId']}:{preview['action']}:{clean_hash[:24]}"
        with self._salesforce_operation(
            clean_key,
            "location_lifecycle_order",
            target,
            clean_hash,
            track_provider_attempt=True,
        ) as prior:
            if prior is not None:
                return {**prior, "duplicate": True, "idempotencyKey": clean_key}
            self._mark_salesforce_provider_attempt(
                clean_key,
                "location_lifecycle_order",
                target,
                clean_hash,
                evidence={"providerAttempted": True},
            )
            reclassification = preview.get("orderToReclassify")
            try:
                if isinstance(reclassification, dict) and reclassification.get("Id"):
                    order_id = _required_id(
                        str(reclassification["Id"]),
                        "order to reclassify id",
                    )
                    self._request(
                        "PATCH",
                        f"/sobjects/NovaPOS_Order__c/{order_id}",
                        json={
                            "RecordTypeId": preview["orderFields"]["RecordTypeId"],
                            "Existing_Order_Type__c": preview["orderFields"][
                                "Existing_Order_Type__c"
                            ],
                        },
                    )
                else:
                    created = self._request(
                        "POST",
                        "/sobjects/NovaPOS_Order__c",
                        json=dict(preview["orderFields"]),
                    )
                    order_id = _required_id(
                        str(created.get("id") or ""),
                        "created order id",
                    )
            except SalesforceUnavailableError:
                recovered = self.location_lifecycle_order_preview(
                    ticket_id,
                    account_id,
                    salesforce_location_ids,
                    action,
                    chargify_subscription_id,
                    monthly_rate_cents=monthly_rate_cents,
                    merchant_provider=merchant_provider,
                ).get("duplicateOrder")
                if not isinstance(recovered, dict) or not recovered.get("Id"):
                    raise
                order_id = _required_id(str(recovered["Id"]), "recovered order id")

            records = self.lookup("order", order_id, limit=1)["records"]
            approval = self._order_approval_state(order_id)
            if (
                len(records) != 1
                or not self._location_lifecycle_order_readback_matches(
                    dict(records[0]),
                    preview["orderFields"],
                    allow_different_billing_date=bool(reclassification),
                )
                or approval.get("submitted")
            ):
                raise SalesforceUnavailableError(
                    "Salesforce lifecycle order readback or no-approval guarantee was not verified; "
                    "do not recreate or submit the order"
                )
            result = {
                **preview,
                "status": "completed",
                "created": not bool(reclassification),
                "reclassified": bool(reclassification),
                "duplicate": False,
                "verified": True,
                "orderId": order_id,
                "readback": dict(records[0]),
                "approval": approval,
                "approvalSubmitted": False,
                "idempotencyKey": clean_key,
            }
            self._complete_salesforce_operation(
                clean_key,
                "location_lifecycle_order",
                target,
                clean_hash,
                result,
            )
            return result

    @staticmethod
    def _location_lifecycle_order_readback_matches(
        order: Mapping[str, Any],
        expected: Mapping[str, Any],
        *,
        allow_different_billing_date: bool = False,
    ) -> bool:
        identity_matches = (
            str(order.get("Account__c") or "") == str(expected.get("Account__c") or "")
            and str(order.get("RecordTypeId") or "") == str(expected.get("RecordTypeId") or "")
            and str(order.get("Description__c") or "").strip()
            == str(expected.get("Description__c") or "").strip()
            and _normalized_picklist_text(order.get("Existing_Order_Type__c"))
            == _normalized_picklist_text(expected.get("Existing_Order_Type__c"))
            and _exact_location_csv(order.get("Location_I_D__c"))
            == _exact_location_csv(expected.get("Location_I_D__c"))
            and _numeric_identifier(order.get("Chargify_Subscription_ID__c"))
            == _numeric_identifier(expected.get("Chargify_Subscription_ID__c"))
            and _integer_identifier(order.get("Total_Number_of_Locations_for_this_order__c"))
            == _integer_identifier(expected.get("Total_Number_of_Locations_for_this_order__c"))
        )
        if not identity_matches:
            return False
        actual_billing_date = str(order.get("Billing_Start_Date1__c") or "")
        expected_billing_date = str(expected.get("Billing_Start_Date1__c") or "")
        if not allow_different_billing_date:
            return actual_billing_date == expected_billing_date
        try:
            _salesforce_date(actual_billing_date, "Billing_Start_Date1__c")
        except SalesforceScopeError:
            return False
        return True

    @staticmethod
    def _location_lifecycle_order_business_identity_matches(
        order: Mapping[str, Any],
        expected: Mapping[str, Any],
        *,
        allow_different_billing_date: bool = False,
    ) -> bool:
        identity_matches = (
            str(order.get("Account__c") or "")
            == str(expected.get("Account__c") or "")
            and str(order.get("Description__c") or "").strip()
            == str(expected.get("Description__c") or "").strip()
            and _exact_location_csv(order.get("Location_I_D__c"))
            == _exact_location_csv(expected.get("Location_I_D__c"))
            and _numeric_identifier(order.get("Chargify_Subscription_ID__c"))
            == _numeric_identifier(expected.get("Chargify_Subscription_ID__c"))
            and _integer_identifier(
                order.get("Total_Number_of_Locations_for_this_order__c")
            )
            == _integer_identifier(
                expected.get("Total_Number_of_Locations_for_this_order__c")
            )
        )
        if not identity_matches:
            return False
        actual_billing_date = str(order.get("Billing_Start_Date1__c") or "")
        expected_billing_date = str(expected.get("Billing_Start_Date1__c") or "")
        if not allow_different_billing_date:
            return actual_billing_date == expected_billing_date
        try:
            _salesforce_date(actual_billing_date, "Billing_Start_Date1__c")
        except SalesforceScopeError:
            return False
        return True

    def reactivation_order_approval_preview(
        self,
        ticket_id: str,
        order_id: str,
    ) -> dict[str, Any]:
        """Reject the retired reactivation approval path."""

        raise SalesforceScopeError(
            "Salesforce approval is prohibited for location reactivation orders; "
            "use location_lifecycle_order_preview/apply"
        )

    def apply_reactivation_order_approval(
        self,
        ticket_id: str,
        order_id: str,
        *,
        idempotency_key: str,
        preview_hash: str,
    ) -> dict[str, Any]:
        """Reject the retired reactivation approval path."""

        raise SalesforceScopeError(
            "Salesforce approval is prohibited for location reactivation orders; "
            "use location_lifecycle_order_preview/apply"
        )

    def update_billing_location_rate(
        self,
        location_id: str,
        monthly_rate_cents: int,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Set only NovaPOS_Location__c.Bill_Amount__c with exact readback."""

        clean_id = _required_id(location_id, "location_id")
        clean_key = _required_idempotency_key(idempotency_key)
        clean_cents = _required_positive_cents(monthly_rate_cents, "monthly_rate_cents")
        before_records = self.lookup("location", clean_id, limit=1)["records"]
        if len(before_records) != 1:
            raise SalesforceScopeError("location_id did not resolve to exactly one Salesforce location")
        before = dict(before_records[0])
        if _decimal_currency_field_to_cents(before.get("Bill_Amount__c")) == clean_cents:
            return {
                "ok": True,
                "updated": False,
                "duplicate": True,
                "verified": True,
                "id": clean_id,
                "idempotencyKey": clean_key,
                "field": "Bill_Amount__c",
                "monthlyRateCents": clean_cents,
                "before": before,
                "readback": before,
            }
        desired_amount = float((Decimal(clean_cents) / Decimal(100)).quantize(Decimal("0.01")))
        self._request(
            "PATCH",
            f"/sobjects/NovaPOS_Location__c/{clean_id}",
            json={"Bill_Amount__c": desired_amount},
        )
        readback_records = self.lookup("location", clean_id, limit=1)["records"]
        if len(readback_records) != 1:
            raise SalesforceUnavailableError("Salesforce location rate readback was unavailable; do not retry")
        readback = dict(readback_records[0])
        if _decimal_currency_field_to_cents(readback.get("Bill_Amount__c")) != clean_cents:
            raise SalesforceUnavailableError(
                "Salesforce location rate readback did not match; do not retry until the record is read again"
            )
        return {
            "ok": True,
            "updated": True,
            "duplicate": False,
            "verified": True,
            "id": clean_id,
            "idempotencyKey": clean_key,
            "field": "Bill_Amount__c",
            "monthlyRateCents": clean_cents,
            "before": before,
            "readback": readback,
        }

    def account_closure_preview(
        self,
        ticket_id: str,
        account_id: str,
        closed_nova_location_ids: list[int],
        nova_active_location_ids: list[int],
        maxio_reconciliation_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        """Preview Account deactivation after exact location/order reconciliation."""

        clean_account_id = _required_id(account_id, "account_id")
        ticket = self._assert_account_cancellation_ticket(ticket_id, clean_account_id)
        account = self.read_billing_account(clean_account_id)["record"]
        locations = self.read_account_locations(clean_account_id)["records"]
        closed_location_ids = _unique_nova_location_ids(
            closed_nova_location_ids,
            "closed_nova_location_ids",
        )
        if not closed_location_ids:
            raise SalesforceScopeError(
                "closed_nova_location_ids must preserve the exact non-storage Nova "
                "location set verified before the account close"
            )
        remaining_nova_active_ids = _unique_nova_location_ids(
            nova_active_location_ids,
            "nova_active_location_ids",
            allow_empty=True,
        )
        if remaining_nova_active_ids:
            raise SalesforceScopeError(
                "Account closure requires Nova BillingAutomation to show zero active "
                "non-storage locations after reconciliation"
            )
        active_locations = [
            location
            for location in locations
            if _normalized_text(str(location.get("Status__c") or "")) == "active"
            and not _is_storage_location(location)
        ]
        if active_locations:
            raise SalesforceScopeError(
                "Account closure requires Salesforce to show zero active non-storage "
                "locations before the Account is deactivated"
            )
        salesforce_locations_by_nova_id: dict[str, list[str]] = {}
        for location in locations:
            if _is_storage_location(location):
                continue
            nova_location_id = _normalized_location_id(location.get("Location_ID__c"))
            if nova_location_id:
                salesforce_locations_by_nova_id.setdefault(nova_location_id, []).append(
                    str(location.get("Id") or "")
                )
        unresolved_ids = [
            location_id
            for location_id in closed_location_ids
            if len(salesforce_locations_by_nova_id.get(location_id, [])) != 1
        ]
        if unresolved_ids:
            raise SalesforceScopeError(
                "Account closure requires one exact non-storage Salesforce location "
                "for every closed Nova location; reconcile duplicate or missing rows first"
            )

        ticket_number = str(ticket.get("Name") or ticket_id).strip()
        order_coverage = _ticket_cancellation_order_coverage(
            self.read_account_orders(clean_account_id)["records"],
            ticket_number,
        )
        if (
            order_coverage["locationIds"] != closed_location_ids
            or order_coverage["locationOrderQuantityTotal"] != len(closed_location_ids)
        ):
            raise SalesforceScopeError(
                "Account closure location total does not match the exact ticket-linked "
                "cancellation-order locations and quantities; reconcile official Nova "
                "active locations, Salesforce non-storage locations, and Maxio location "
                "components before closing the Account"
            )
        maxio_evidence = _maxio_account_reconciliation_evidence(
            maxio_reconciliation_evidence
        )
        if not set(order_coverage["subscriptionIds"]).issubset(
            set(maxio_evidence["subscriptionIds"])
        ):
            raise SalesforceScopeError(
                "Account closure Maxio reconciliation must include every "
                "subscription represented by the ticket-linked cancellation orders"
            )
        if (
            maxio_evidence["openSubscriptionIds"]
            or maxio_evidence["openLocationComponentCount"] != 0
        ):
            raise SalesforceScopeError(
                "Account closure requires Maxio reconciliation to show no open "
                "subscriptions and zero open location-component quantity"
            )
        # Real_Account_Status__c and NovaPOS_Active__c are calculated/read-only
        # fields in the production org. Status__c is the authoritative editable
        # lifecycle field used by the Rainfall dashboard.
        desired = {"Status__c": "Inactive"}
        duplicate = all(str(account.get(key) or "").strip() == value for key, value in desired.items())
        plan = {
            "operation": "salesforce_account_closure",
            "ticketId": str(ticket.get("Id") or ticket_id),
            "ticketNumber": str(ticket.get("Name") or ""),
            "accountId": clean_account_id,
            "companyUsername": str(account.get("Company_Username__c") or ""),
            "before": {
                "Status__c": account.get("Status__c"),
                "Real_Account_Status__c": account.get("Real_Account_Status__c"),
                "NovaPOS_Active__c": account.get("NovaPOS_Active__c"),
            },
            "desired": desired,
            "locationCount": len(locations),
            "activeLocationCount": 0,
            "closedNovaLocationIds": closed_location_ids,
            "totalLocationCount": len(closed_location_ids),
            "locationOrderQuantityTotal": order_coverage[
                "locationOrderQuantityTotal"
            ],
            "locationOrderRecordCount": order_coverage["orderCount"],
            "locationOrderIds": order_coverage["orderIds"],
            "locationOrderCoverageVerified": True,
            "novaActiveLocationIds": remaining_nova_active_ids,
            "maxioReconciliationEvidence": maxio_evidence,
            "crossSystemLocationCountsMatch": True,
            "duplicate": duplicate,
        }
        return {
            "ok": True,
            "status": "preview",
            "verified": True,
            **plan,
            "planHash": _stable_plan_hash(plan),
            "writesPerformed": False,
        }

    def apply_account_closure(
        self,
        ticket_id: str,
        account_id: str,
        closed_nova_location_ids: list[int],
        nova_active_location_ids: list[int],
        maxio_reconciliation_evidence: dict[str, Any],
        *,
        idempotency_key: str,
        preview_hash: str,
    ) -> dict[str, Any]:
        """Apply the exact previewed editable Account status and read lifecycle fields back."""

        clean_key = _required_idempotency_key(idempotency_key)
        clean_hash = _required_preview_hash(preview_hash)
        preview = self.account_closure_preview(
            ticket_id,
            account_id,
            closed_nova_location_ids,
            nova_active_location_ids,
            maxio_reconciliation_evidence,
        )
        if preview["planHash"] != clean_hash:
            raise SalesforceScopeError("preview_hash does not match the current Account closure plan")
        if preview["duplicate"]:
            return {
                **preview,
                "status": "completed",
                "updated": False,
                "duplicate": True,
                "idempotencyKey": clean_key,
                "readback": preview["before"],
            }
        clean_account_id = _required_id(account_id, "account_id")
        self._request(
            "PATCH",
            f"/sobjects/Account/{clean_account_id}",
            json=dict(preview["desired"]),
        )
        readback = self.read_billing_account(clean_account_id)["record"]
        if any(str(readback.get(key) or "").strip() != value for key, value in preview["desired"].items()):
            raise SalesforceUnavailableError(
                "Salesforce Account closure readback did not match; do not retry until the Account is read again"
            )
        return {
            **preview,
            "status": "completed",
            "updated": True,
            "duplicate": False,
            "idempotencyKey": clean_key,
            "readback": readback,
        }

    def cancellation_order_preview(
        self,
        ticket_id: str,
        account_id: str,
        salesforce_location_ids: list[str],
        official_nova_location_ids: list[int],
        maxio_deallocation_evidence: list[dict[str, Any]],
        cancellation_reason: str,
        *,
        notes: str = "",
    ) -> dict[str, Any]:
        """Preview full-account cancellation orders grouped one per subscription."""

        return self._cancellation_orders_preview(
            ticket_id,
            account_id,
            cancellation_reason,
            notes=notes,
            scope="account",
            selected_location_record_ids=salesforce_location_ids,
            official_nova_location_ids=official_nova_location_ids,
            maxio_deallocation_evidence=maxio_deallocation_evidence,
        )

    def location_cancellation_order_preview(
        self,
        ticket_id: str,
        account_id: str,
        salesforce_location_ids: list[str],
        maxio_deallocation_evidence: list[dict[str, Any]],
        cancellation_reason: str,
        *,
        notes: str = "",
    ) -> dict[str, Any]:
        """Preview exact partial-location cancellation orders grouped one per subscription."""

        return self._cancellation_orders_preview(
            ticket_id,
            account_id,
            cancellation_reason,
            notes=notes,
            scope="location",
            selected_location_record_ids=salesforce_location_ids,
            official_nova_location_ids=None,
            maxio_deallocation_evidence=maxio_deallocation_evidence,
        )

    def _cancellation_orders_preview(
        self,
        ticket_id: str,
        account_id: str,
        cancellation_reason: str,
        *,
        notes: str,
        scope: str,
        selected_location_record_ids: list[str],
        official_nova_location_ids: list[int] | None,
        maxio_deallocation_evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        clean_account_id = _required_id(account_id, "account_id")
        if scope not in {"account", "location"}:
            raise SalesforceScopeError("cancellation order scope is not supported")
        ticket = self._assert_account_cancellation_ticket(ticket_id, clean_account_id)
        clean_reason = _bounded(cancellation_reason, "cancellation_reason", 255)
        default_notes = (
            f"{'Account' if scope == 'account' else 'Location'} cancellation requested "
            f"on ticket {ticket.get('Name') or ''}."
        )
        clean_notes = _bounded(notes or default_notes, "notes", 5000)
        account = self.read_billing_account(clean_account_id)["record"]
        all_locations = self.read_account_locations(clean_account_id)["records"]
        if not all_locations:
            raise SalesforceScopeError(
                f"{scope.title()} cancellation order requires at least one Salesforce location"
            )

        locations_by_id = {
            str(location.get("Id") or ""): dict(location)
            for location in all_locations
            if SALESFORCE_ID.fullmatch(str(location.get("Id") or ""))
        }
        selected_ids = _unique_salesforce_record_ids(
            selected_location_record_ids,
            "salesforce_location_ids",
            limit=100,
        )
        if not selected_ids:
            raise SalesforceScopeError(
                "salesforce_location_ids must select at least one exact deallocated location"
            )
        missing_ids = sorted(set(selected_ids) - set(locations_by_id))
        if missing_ids:
            raise SalesforceScopeError(
                "salesforce_location_ids must all belong to the requested Account"
            )
        locations = [locations_by_id[location_id] for location_id in selected_ids]
        remaining_active = sorted(
            str(location.get("Id") or "")
            for location in all_locations
            if str(location.get("Id") or "") not in set(selected_ids)
            and _normalized_text(str(location.get("Status__c") or "")) == "active"
        )
        if scope == "location" and not remaining_active:
            raise SalesforceScopeError(
                "Location cancellation order requires at least one other active location; "
                "use the full-account cancellation workflow for the last location"
            )
        if scope == "account":
            any_active = sorted(
                str(location.get("Id") or "")
                for location in all_locations
                if _normalized_text(str(location.get("Status__c") or "")) == "active"
            )
            if any_active:
                raise SalesforceScopeError(
                    "Account cancellation order requires every Salesforce location "
                    "to be non-active"
                )
            remaining_active = []

        active_locations = sorted(
            str(location.get("Id") or "")
            for location in locations
            if _normalized_text(str(location.get("Status__c") or "")) == "active"
        )
        if active_locations:
            raise SalesforceScopeError(
                f"{scope.title()} cancellation order requires every selected Salesforce "
                "location to be non-active"
            )

        normalized_locations: list[dict[str, Any]] = []
        seen_location_numbers: set[str] = set()
        for location in locations:
            location_record_id = _required_id(
                str(location.get("Id") or ""),
                "Salesforce location id",
            )
            location_name = str(location.get("Name") or "").strip()
            if (
                _normalized_text(str(location.get("Status__c") or "")) == "storage"
                or re.search(r"\bstorages?\b", location_name, re.IGNORECASE)
            ):
                raise SalesforceScopeError(
                    "Cancellation orders may include billable locations only; "
                    f"{location_record_id} is a storage row"
                )
            location_number = _normalized_location_id(location.get("Location_ID__c"))
            if not location_number:
                raise SalesforceScopeError(
                    "Cancellation order requires a numeric Nova Location ID for every "
                    "selected Salesforce location"
                )
            if location_number in seen_location_numbers:
                raise SalesforceScopeError(
                    "Cancellation order requires one unambiguous Salesforce record per "
                    "Nova Location ID"
                )
            seen_location_numbers.add(location_number)
            subscription_id = _numeric_identifier(
                location.get("Chargify_Subscription_ID__c")
            )
            if subscription_id is None:
                raise SalesforceScopeError(
                    "Cancellation order requires a positive Chargify subscription ID on "
                    f"every selected Salesforce location; {location_record_id} is missing it"
                )
            normalized_locations.append(
                {
                    "locationRecordId": location_record_id,
                    "locationId": location_number,
                    "subscriptionId": subscription_id,
                }
            )

        selected_nova_location_ids = sorted(
            (str(row["locationId"]) for row in normalized_locations),
            key=int,
        )
        if scope == "account":
            expected_nova_location_ids = _unique_nova_location_ids(
                official_nova_location_ids,
                "official_nova_location_ids",
            )
            if not expected_nova_location_ids:
                raise SalesforceScopeError(
                    "official_nova_location_ids must preserve the exact active "
                    "non-storage Nova locations verified before account closing"
                )
            if selected_nova_location_ids != expected_nova_location_ids:
                raise SalesforceScopeError(
                    "Full-account cancellation requires selected Salesforce locations "
                    "to exactly match the official Nova active non-storage location set; "
                    "reconcile Salesforce and Maxio before creating cancellation orders"
                )
        else:
            expected_nova_location_ids = selected_nova_location_ids

        record_type = self._resolve_cancellation_order_record_type()
        record_type_id = str(record_type["Id"])
        reason_value = self._resolve_order_picklist_value(
            record_type_id,
            "Reason_for_cancellation__c",
            clean_reason,
        )
        order_type_value = self._resolve_order_picklist_value(
            record_type_id,
            "Existing_Order_Type__c",
            CANCELLATION_ORDER_TYPE_LABEL,
            required=False,
        )
        owner_id = str(
            account.get("Nova_Account_Manager__c") or account.get("OwnerId") or ""
        ).strip()
        existing = self.read_account_orders(clean_account_id)["records"]
        groups: dict[int, list[dict[str, Any]]] = {}
        for location in normalized_locations:
            groups.setdefault(int(location["subscriptionId"]), []).append(location)
        evidence_by_subscription = _maxio_location_deallocation_evidence(
            maxio_deallocation_evidence
        )
        if set(evidence_by_subscription) != set(groups):
            raise SalesforceScopeError(
                "Maxio deallocation evidence must contain exactly one entry for every "
                "selected Chargify subscription"
            )

        order_plans: list[dict[str, Any]] = []
        scope_label = "Account" if scope == "account" else "Location"
        for subscription_id in sorted(groups):
            group = sorted(groups[subscription_id], key=lambda row: int(row["locationId"]))
            location_numbers = [str(row["locationId"]) for row in group]
            location_record_ids = sorted(str(row["locationRecordId"]) for row in group)
            location_csv = ",".join(location_numbers)
            maxio_evidence = evidence_by_subscription[subscription_id]
            deallocation_count = int(
                maxio_evidence["locationComponentDeallocationCount"]
            )
            if deallocation_count != len(location_numbers):
                raise SalesforceScopeError(
                    "Selected Salesforce billable-location count must exactly match "
                    "the Maxio location-component deallocation count for subscription "
                    f"{subscription_id}; storage and other component quantities do not count"
                )
            contract_name = (
                f"-{deallocation_count} Location"
                f"{'s' if deallocation_count != 1 else ''}. Billing Automation Order"
            )
            description = (
                f"{scope_label} cancellation under ticket "
                f"{ticket.get('Name') or ticket_id}. Locations: {location_csv}. "
                f"Chargify subscription: {subscription_id}. "
                "Maxio location-component evidence: "
                f"{maxio_evidence['maxioPreviewHash']}"
            )
            order_fields: dict[str, Any] = {
                "Account__c": clean_account_id,
                "RecordTypeId": record_type_id,
                "Contract_Name__c": contract_name,
                "Description__c": description,
                "Sales_Additional_Notes__c": clean_notes,
                "Cancellation_Order_Notes__c": clean_notes,
                "Reason_for_cancellation__c": reason_value,
                "Total_Number_of_Locations_for_this_order__c": -deallocation_count,
                "Location_I_D__c": location_csv,
                "Chargify_Subscription_ID__c": subscription_id,
                "Billing_Start_Date1__c": datetime.now(timezone.utc).date().isoformat(),
            }
            if order_type_value:
                order_fields["Existing_Order_Type__c"] = order_type_value
            if SALESFORCE_ID.fullmatch(owner_id):
                order_fields["Order_Assigned_To_c__c"] = owner_id
            core_matches = [
                order
                for order in existing
                if str(order.get("RecordTypeId") or "") == record_type_id
                and _exact_location_csv(order.get("Location_I_D__c"))
                == location_csv
                and str(order.get("Reason_for_cancellation__c") or "") == reason_value
                and _numeric_identifier(
                    order.get("Chargify_Subscription_ID__c")
                )
                == subscription_id
                and _integer_identifier(
                    order.get("Total_Number_of_Locations_for_this_order__c")
                )
                == -deallocation_count
                and str(order.get("Contract_Name__c") or "") == contract_name
            ]
            duplicate_order = next(
                (
                    order
                    for order in core_matches
                    if str(order.get("Description__c") or "") == description
                ),
                None,
            )
            blank_evidence_orders = [
                order
                for order in core_matches
                if not str(order.get("Description__c") or "").strip()
            ]
            if duplicate_order is None and len(core_matches) > 1:
                raise SalesforceScopeError(
                    "More than one existing cancellation order has the same exact Account, "
                    "subscription, location, reason, and quantity; repair the duplicate "
                    "Salesforce orders before continuing"
                )
            if duplicate_order is None and core_matches and not blank_evidence_orders:
                raise SalesforceScopeError(
                    "An existing cancellation order has the same exact Account, subscription, "
                    "location, reason, and quantity but different nonblank evidence; do not "
                    "create a duplicate order"
                )
            evidence_repair_order = (
                blank_evidence_orders[0]
                if duplicate_order is None and len(blank_evidence_orders) == 1
                else None
            )
            order_plans.append(
                {
                    "subscriptionId": subscription_id,
                    "locationRecordIds": location_record_ids,
                    "locationIds": location_numbers,
                    "maxioDeallocationEvidence": maxio_evidence,
                    "orderFields": order_fields,
                    "duplicateOrder": duplicate_order,
                    "evidenceRepairOrder": evidence_repair_order,
                }
            )

        location_ids = selected_nova_location_ids
        location_record_ids = sorted(
            str(location["locationRecordId"]) for location in normalized_locations
        )
        plan: dict[str, Any] = {
            "operation": f"salesforce_{scope}_cancellation_orders",
            "scope": scope,
            "ticketId": str(ticket.get("Id") or ticket_id),
            "ticketNumber": str(ticket.get("Name") or ""),
            "accountId": clean_account_id,
            "companyUsername": str(account.get("Company_Username__c") or ""),
            "recordType": _bounded_record(record_type),
            "locationRecordIds": location_record_ids,
            "locationIds": location_ids,
            "remainingActiveLocationRecordIds": remaining_active,
            "subscriptionIds": sorted(groups),
            "maxioDeallocationEvidence": [
                evidence_by_subscription[subscription_id]
                for subscription_id in sorted(evidence_by_subscription)
            ],
            "locationComponentDeallocationCount": sum(
                int(row["locationComponentDeallocationCount"])
                for row in evidence_by_subscription.values()
            ),
            "totalLocationCount": len(expected_nova_location_ids),
            "locationOrderQuantityTotal": sum(
                int(row["locationComponentDeallocationCount"])
                for row in evidence_by_subscription.values()
            ),
            "locationOrderCoverageVerified": (
                location_ids == expected_nova_location_ids
                and sum(
                    int(row["locationComponentDeallocationCount"])
                    for row in evidence_by_subscription.values()
                )
                == len(expected_nova_location_ids)
            ),
            "orderCount": len(order_plans),
            "evidenceRepairCount": sum(
                1 for row in order_plans if row.get("evidenceRepairOrder")
            ),
            "orders": order_plans,
            "oneOrderPerSubscription": True,
            "allLocationsSubscriptionLinked": True,
        }
        if len(order_plans) == 1:
            plan["orderFields"] = dict(order_plans[0]["orderFields"])
            plan["duplicateOrder"] = order_plans[0]["duplicateOrder"]
            plan["evidenceRepairOrder"] = order_plans[0]["evidenceRepairOrder"]
        return {
            "ok": True,
            "status": "preview",
            "verified": True,
            **plan,
            "planHash": _stable_plan_hash(plan),
            "writesPerformed": False,
        }

    def apply_cancellation_order(
        self,
        ticket_id: str,
        account_id: str,
        salesforce_location_ids: list[str],
        official_nova_location_ids: list[int],
        maxio_deallocation_evidence: list[dict[str, Any]],
        cancellation_reason: str,
        *,
        notes: str = "",
        idempotency_key: str,
        preview_hash: str,
    ) -> dict[str, Any]:
        """Create full-account cancellation orders one per subscription and verify each."""

        clean_key = _required_idempotency_key(idempotency_key)
        clean_hash = _required_preview_hash(preview_hash)
        preview = self.cancellation_order_preview(
            ticket_id,
            account_id,
            salesforce_location_ids,
            official_nova_location_ids,
            maxio_deallocation_evidence,
            cancellation_reason,
            notes=notes,
        )
        if preview["planHash"] != clean_hash:
            raise SalesforceScopeError("preview_hash does not match the current cancellation-order plan")
        return self._apply_cancellation_orders(
            preview,
            idempotency_key=clean_key,
            preview_hash=clean_hash,
        )

    def apply_location_cancellation_order(
        self,
        ticket_id: str,
        account_id: str,
        salesforce_location_ids: list[str],
        maxio_deallocation_evidence: list[dict[str, Any]],
        cancellation_reason: str,
        *,
        notes: str = "",
        idempotency_key: str,
        preview_hash: str,
    ) -> dict[str, Any]:
        """Create partial-location cancellation orders one per subscription and verify each."""

        clean_key = _required_idempotency_key(idempotency_key)
        clean_hash = _required_preview_hash(preview_hash)
        preview = self.location_cancellation_order_preview(
            ticket_id,
            account_id,
            salesforce_location_ids,
            maxio_deallocation_evidence,
            cancellation_reason,
            notes=notes,
        )
        if preview["planHash"] != clean_hash:
            raise SalesforceScopeError(
                "preview_hash does not match the current location-cancellation-order plan"
            )
        return self._apply_cancellation_orders(
            preview,
            idempotency_key=clean_key,
            preview_hash=clean_hash,
        )

    def _apply_cancellation_orders(
        self,
        preview: dict[str, Any],
        *,
        idempotency_key: str,
        preview_hash: str,
    ) -> dict[str, Any]:
        clean_key = _required_idempotency_key(idempotency_key)
        clean_hash = _required_preview_hash(preview_hash)
        operation = f"{preview['scope']}_cancellation_orders"
        target = f"{preview['accountId']}:{preview['scope']}:{clean_hash[:24]}"
        with self._salesforce_operation(
            clean_key,
            operation,
            target,
            clean_hash,
        ) as prior:
            if prior is not None:
                return {**prior, "duplicate": True, "idempotencyKey": clean_key}

            results: list[dict[str, Any]] = []
            for order_plan in preview["orders"]:
                duplicate_order = order_plan.get("duplicateOrder")
                evidence_repair_order = order_plan.get("evidenceRepairOrder")
                created = False
                evidence_repaired = False
                if isinstance(duplicate_order, dict) and duplicate_order.get("Id"):
                    order_id = _required_id(
                        str(duplicate_order["Id"]),
                        "existing order id",
                    )
                elif (
                    isinstance(evidence_repair_order, dict)
                    and evidence_repair_order.get("Id")
                ):
                    order_id = _required_id(
                        str(evidence_repair_order["Id"]),
                        "existing order id",
                    )
                    self._request(
                        "PATCH",
                        f"/sobjects/NovaPOS_Order__c/{order_id}",
                        json={
                            "Description__c": str(
                                order_plan["orderFields"]["Description__c"]
                            )
                        },
                    )
                    evidence_repaired = True
                else:
                    created_result = self._request(
                        "POST",
                        "/sobjects/NovaPOS_Order__c",
                        json=dict(order_plan["orderFields"]),
                    )
                    order_id = _required_id(
                        str(created_result.get("id") or ""),
                        "created order id",
                    )
                    created = True

                approval = self._order_approval_state(order_id)
                approval_applicable = True
                provider_result: Any = None
                if not approval.get("submitted"):
                    try:
                        provider_result = self._request(
                            "POST",
                            "/process/approvals/",
                            json={
                                "requests": [
                                    {
                                        "actionType": "Submit",
                                        "contextId": order_id,
                                        "comments": (
                                            f"Submitting {preview['scope']} cancellation order "
                                            f"for ticket {preview['ticketNumber']} and "
                                            f"Chargify subscription "
                                            f"{order_plan['subscriptionId']}."
                                        ),
                                        "nextApproverIds": [],
                                    }
                                ]
                            },
                        )
                    except SalesforceUnavailableError as exc:
                        if "NO_APPLICABLE_PROCESS" not in str(exc):
                            raise
                        approval_applicable = False
                        provider_result = {
                            "success": False,
                            "errorCode": "NO_APPLICABLE_PROCESS",
                            "disposition": "not_applicable",
                        }
                    else:
                        if not _approval_provider_success(provider_result):
                            raise SalesforceUnavailableError(
                                "Salesforce created the cancellation order but rejected "
                                "approval submission; do not recreate it"
                            )
                        for attempt in range(4):
                            approval = self._order_approval_state(order_id)
                            if approval.get("submitted"):
                                break
                            if attempt < 3:
                                time.sleep(0.5)

                records = self.lookup("order", order_id, limit=1)["records"]
                if (
                    len(records) != 1
                    or not self._cancellation_order_readback_matches(
                        dict(records[0]),
                        order_plan,
                    )
                    or (approval_applicable and not approval.get("submitted"))
                ):
                    raise SalesforceUnavailableError(
                        "Salesforce cancellation order, subscription link, location scope, "
                        "or applicable approval readback was not verified; do not retry by "
                        "creating another order"
                    )
                results.append(
                    {
                        "subscriptionId": int(order_plan["subscriptionId"]),
                        "locationRecordIds": list(order_plan["locationRecordIds"]),
                        "locationIds": list(order_plan["locationIds"]),
                        "orderId": order_id,
                        "created": created,
                        "updated": evidence_repaired,
                        "evidenceRepaired": evidence_repaired,
                        "duplicate": not created and not evidence_repaired,
                        "approvalSubmitted": bool(approval.get("submitted")),
                        "approvalApplicable": approval_applicable,
                        "approvalDisposition": (
                            "submitted"
                            if approval.get("submitted")
                            else "not_applicable"
                        ),
                        "approval": approval,
                        "readback": dict(records[0]),
                        "providerResult": _bounded_record(provider_result),
                    }
                )

            created_count = sum(1 for result in results if result["created"])
            evidence_repaired_count = sum(
                1 for result in results if result["evidenceRepaired"]
            )
            result: dict[str, Any] = {
                **preview,
                "status": "completed",
                "created": created_count > 0,
                "createdCount": created_count,
                "updated": evidence_repaired_count > 0,
                "evidenceRepairedCount": evidence_repaired_count,
                "duplicate": created_count == 0 and evidence_repaired_count == 0,
                "duplicateCount": sum(1 for row in results if row["duplicate"]),
                "verified": True,
                "idempotencyKey": clean_key,
                "orderIds": [row["orderId"] for row in results],
                "orders": results,
                "readbacks": [row["readback"] for row in results],
                "allOrdersSubscriptionLinked": all(
                    _numeric_identifier(
                        row["readback"].get("Chargify_Subscription_ID__c")
                    )
                    == row["subscriptionId"]
                    for row in results
                ),
            }
            if len(results) == 1:
                single = results[0]
                result.update(
                    {
                        "orderId": single["orderId"],
                        "approvalSubmitted": single["approvalSubmitted"],
                        "approvalApplicable": single["approvalApplicable"],
                        "approvalDisposition": single["approvalDisposition"],
                        "approval": single["approval"],
                        "readback": single["readback"],
                        "providerResult": single["providerResult"],
                    }
                )
            self._complete_salesforce_operation(
                clean_key,
                operation,
                target,
                clean_hash,
                result,
            )
            return result

    @staticmethod
    def _cancellation_order_readback_matches(
        record: dict[str, Any],
        order_plan: dict[str, Any],
    ) -> bool:
        expected = dict(order_plan["orderFields"])
        return bool(
            str(record.get("Account__c") or "") == str(expected["Account__c"])
            and str(record.get("RecordTypeId") or "") == str(expected["RecordTypeId"])
            and str(record.get("Contract_Name__c") or "")
            == str(expected["Contract_Name__c"])
            and str(record.get("Description__c") or "")
            == str(expected["Description__c"])
            and _exact_location_csv(record.get("Location_I_D__c"))
            == str(expected["Location_I_D__c"])
            and _numeric_identifier(record.get("Chargify_Subscription_ID__c"))
            == int(order_plan["subscriptionId"])
            and _integer_identifier(
                record.get("Total_Number_of_Locations_for_this_order__c")
            )
            == int(expected["Total_Number_of_Locations_for_this_order__c"])
            and str(record.get("Reason_for_cancellation__c") or "")
            == str(expected["Reason_for_cancellation__c"])
        )

    def post_account_cancellation_chatter(
        self,
        ticket_id: str,
        account_id: str,
        body: str,
    ) -> dict[str, Any]:
        """Post lifecycle progress to Chatter after validating the cross-lane cancellation ticket."""

        clean_account_id = _required_id(account_id, "account_id")
        self._assert_account_cancellation_ticket(ticket_id, clean_account_id)
        return self.post_ticket_chatter(ticket_id, body, allowed_record_types=None)

    def finalize_account_cancellation(
        self,
        ticket_id: str,
        account_id: str,
        resolution_note: str = "",
        *,
        reply_to_feed_element_id: str = "",
    ) -> dict[str, Any]:
        """Send the fixed closure notice and resolve one verified cancellation ticket."""

        clean_ticket_id = _required_id(ticket_id, "ticket_id")
        clean_account_id = _required_id(account_id, "account_id")
        self._assert_account_cancellation_ticket(clean_ticket_id, clean_account_id)
        email = self.send_account_cancellation_confirmation_email(
            clean_ticket_id,
            clean_account_id,
        )
        if not email.get("verified"):
            raise SalesforceUnavailableError(
                "Account cancellation confirmation email readback did not verify; "
                "do not resolve the ticket"
            )
        resolved = self.resolve_ticket(
            clean_ticket_id,
            resolution_note,
            reply_to_feed_element_id=reply_to_feed_element_id,
            allowed_record_types=None,
        )
        if not resolved.get("verified") or not resolved.get("closed"):
            raise SalesforceUnavailableError(
                "Account cancellation ticket closure readback did not verify"
            )
        return {
            "ok": True,
            "verified": True,
            "ticketId": clean_ticket_id,
            "accountId": clean_account_id,
            "email": email,
            "ticket": resolved,
        }

    def upload_account_cancellation_pdf(
        self,
        ticket_id: str,
        account_id: str,
        file_name: str,
        content_base64: str,
        sha256: str,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Attach one verified cancellation PDF to the exact cross-lane ticket."""

        clean_account_id = _required_id(account_id, "account_id")
        clean_ticket_id = _required_id(ticket_id, "ticket_id")
        self._assert_account_cancellation_ticket(clean_ticket_id, clean_account_id)
        clean_key = _required_idempotency_key(idempotency_key)
        clean_name, clean_digest = _validated_cancellation_pdf_identity(file_name, sha256)
        try:
            content = base64.b64decode(str(content_base64 or ""), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise SalesforceScopeError("content_base64 must be valid base64") from exc
        if not content or len(content) > 10 * 1024 * 1024:
            raise SalesforceScopeError("cancellation PDF must be between 1 byte and 10 MiB")
        if not content.startswith(b"%PDF-"):
            raise SalesforceScopeError("cancellation attachment signature is not PDF")
        if hashlib.sha256(content).hexdigest() != clean_digest:
            raise SalesforceScopeError("sha256 does not match the cancellation PDF")

        for record in self._ticket_content_versions(clean_ticket_id):
            if str(record.get("Title") or "").casefold() != Path(clean_name).stem.casefold():
                continue
            if int(record.get("ContentSize") or 0) != len(content):
                continue
            version_id = _required_id(str(record.get("Id") or ""), "existing ContentVersion id")
            if hashlib.sha256(self._request_bytes(f"/sobjects/ContentVersion/{version_id}/VersionData")).hexdigest() == clean_digest:
                return {
                    "ok": True,
                    "uploaded": False,
                    "duplicate": True,
                    "verified": True,
                    "ticketId": clean_ticket_id,
                    "accountId": clean_account_id,
                    "idempotencyKey": clean_key,
                    "sha256": clean_digest,
                    "contentVersion": record,
                }
            raise SalesforceScopeError("a different PDF with the same title and size is already attached")

        created = self._request(
            "POST",
            "/sobjects/ContentVersion",
            json={
                "Title": Path(clean_name).stem,
                "PathOnClient": clean_name,
                "VersionData": base64.b64encode(content).decode("ascii"),
                "FirstPublishLocationId": clean_ticket_id,
            },
        )
        version_id = _required_id(str(created.get("id") or ""), "created ContentVersion id")
        readback = next(
            (
                record
                for record in self._ticket_content_versions(clean_ticket_id)
                if str(record.get("Id") or "") == version_id
            ),
            None,
        )
        if not readback:
            raise SalesforceUnavailableError(
                "Salesforce accepted the PDF upload but ticket attachment readback was not found; do not retry"
            )
        downloaded = self._request_bytes(f"/sobjects/ContentVersion/{version_id}/VersionData")
        if hashlib.sha256(downloaded).hexdigest() != clean_digest:
            raise SalesforceUnavailableError(
                "Salesforce cancellation PDF readback digest did not match; do not retry"
            )
        return {
            "ok": True,
            "uploaded": True,
            "duplicate": False,
            "verified": True,
            "ticketId": clean_ticket_id,
            "accountId": clean_account_id,
            "idempotencyKey": clean_key,
            "sha256": clean_digest,
            "contentVersion": readback,
        }

    def account_cancellation_pdf_status(
        self,
        ticket_id: str,
        account_id: str,
        file_name: str,
        sha256: str,
    ) -> dict[str, Any]:
        """Read exact cancellation-PDF duplicate and digest evidence without writing."""

        clean_account_id = _required_id(account_id, "account_id")
        clean_ticket_id = _required_id(ticket_id, "ticket_id")
        self._assert_account_cancellation_ticket(clean_ticket_id, clean_account_id)
        clean_name, clean_digest = _validated_cancellation_pdf_identity(file_name, sha256)
        title = Path(clean_name).stem.casefold()
        matching_title: list[dict[str, Any]] = []
        exact_matches: list[dict[str, Any]] = []
        for record in self._ticket_content_versions(clean_ticket_id):
            if str(record.get("Title") or "").casefold() != title:
                continue
            candidate = dict(record)
            version_id = _required_id(str(candidate.get("Id") or ""), "existing ContentVersion id")
            candidate_digest = hashlib.sha256(
                self._request_bytes(f"/sobjects/ContentVersion/{version_id}/VersionData")
            ).hexdigest()
            candidate["sha256"] = candidate_digest
            matching_title.append(candidate)
            if candidate_digest == clean_digest:
                exact_matches.append(candidate)
        return {
            "ok": True,
            "verified": True,
            "duplicate": bool(exact_matches),
            "conflictingTitle": bool(matching_title and not exact_matches),
            "ticketId": clean_ticket_id,
            "accountId": clean_account_id,
            "fileName": clean_name,
            "sha256": clean_digest,
            "contentVersion": exact_matches[0] if exact_matches else None,
            "matchingTitleVersions": matching_title,
            "writesPerformed": False,
        }

    def account_cancellation_email_attachment_status(
        self,
        ticket_id: str,
        account_id: str,
        file_name: str,
        sha256: str,
    ) -> dict[str, Any]:
        """Read exact customer closure-email evidence on one cross-lane cancellation ticket."""

        clean_account_id = _required_id(account_id, "account_id")
        clean_ticket_id = _required_id(ticket_id, "ticket_id")
        self._assert_account_cancellation_ticket(clean_ticket_id, clean_account_id)
        clean_name, clean_digest = _validated_cancellation_email_identity(
            file_name,
            sha256,
        )
        status = self.ticket_attachment_status(
            clean_ticket_id,
            clean_name,
            clean_digest,
            allowed_record_types={
                "1. NOVA Classic",
                "2. Nova Wave",
                "3. Billing",
            },
        )
        return {
            **status,
            "accountId": clean_account_id,
        }

    def upload_account_cancellation_email_attachment(
        self,
        ticket_id: str,
        account_id: str,
        file_name: str,
        content_base64: str,
        sha256: str,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Attach one exact RFC email to the verified cross-lane cancellation ticket."""

        clean_account_id = _required_id(account_id, "account_id")
        clean_ticket_id = _required_id(ticket_id, "ticket_id")
        self._assert_account_cancellation_ticket(clean_ticket_id, clean_account_id)
        clean_name, clean_digest = _validated_cancellation_email_identity(
            file_name,
            sha256,
        )
        result = self.upload_ticket_attachment(
            clean_ticket_id,
            clean_name,
            content_base64,
            clean_digest,
            idempotency_key=idempotency_key,
            allowed_record_types={
                "1. NOVA Classic",
                "2. Nova Wave",
                "3. Billing",
            },
        )
        return {
            **result,
            "accountId": clean_account_id,
        }

    def send_account_cancellation_confirmation_email(
        self,
        ticket_id: str,
        account_id: str,
    ) -> dict[str, Any]:
        """Send one fixed closure notice to the Account primary contact and ticket-listed customer emails."""

        clean_ticket_id = _required_id(ticket_id, "ticket_id")
        clean_account_id = _required_id(account_id, "account_id")
        ticket = self._assert_account_cancellation_ticket(clean_ticket_id, clean_account_id)
        account_result = self._query(
            "SELECT Id,Name,Status__c,NovaPOS_Active__c,Email_Address__c,PrimaryContact__c,"
            "PrimaryContact__r.Id,PrimaryContact__r.Name,PrimaryContact__r.FirstName,"
            "PrimaryContact__r.Email "
            f"FROM Account WHERE Id = '{clean_account_id}' LIMIT 1"
        )
        accounts = [
            dict(record)
            for record in account_result.get("records", [])
            if isinstance(record, dict)
        ]
        if len(accounts) != 1:
            raise SalesforceScopeError("account_id did not resolve to exactly one Salesforce Account")
        account = accounts[0]
        if _normalized_text(str(account.get("Status__c") or "")) != "inactive":
            raise SalesforceScopeError(
                "Account cancellation confirmation requires Salesforce Account status Inactive"
            )

        locations = self.read_account_locations(clean_account_id)["records"]
        active_locations = [
            str(record.get("Id") or "")
            for record in locations
            if _normalized_text(str(record.get("Status__c") or "")) == "active"
        ]
        if active_locations:
            raise SalesforceScopeError(
                "Account cancellation confirmation requires every Salesforce location to be non-active"
            )
        ticket_number = str(ticket.get("Name") or clean_ticket_id).strip()
        cancellation_orders = [
            record
            for record in self.read_account_orders(clean_account_id)["records"]
            if (
                _decimal_currency_field_to_cents(
                    record.get("Total_Number_of_Locations_for_this_order__c")
                )
                or 0
            )
            < 0
        ]
        matched_orders: list[dict[str, Any]] = []
        matched_subscriptions: set[int] = set()
        ticket_marker = re.compile(
            rf"\bticket\s+{re.escape(ticket_number)}\b",
            re.IGNORECASE,
        )
        for order in cancellation_orders:
            description = str(order.get("Description__c") or "")
            if (
                not ticket_marker.search(description)
                or not re.search(
                    r"\bMaxio location-component evidence:\s*[a-f0-9]{64}\b",
                    description,
                    re.IGNORECASE,
                )
            ):
                continue
            subscription_id = _numeric_identifier(
                order.get("Chargify_Subscription_ID__c")
            )
            location_csv = _exact_location_csv(order.get("Location_I_D__c"))
            location_ids = location_csv.split(",") if location_csv else []
            count = _integer_identifier(
                order.get("Total_Number_of_Locations_for_this_order__c")
            )
            expected_contract = (
                f"-{len(location_ids)} Location"
                f"{'s' if len(location_ids) != 1 else ''}. Billing Automation Order"
            )
            if (
                subscription_id is None
                or not location_ids
                or count != -len(location_ids)
                or str(order.get("Contract_Name__c") or "") != expected_contract
                or subscription_id in matched_subscriptions
            ):
                raise SalesforceScopeError(
                    "Account cancellation confirmation found a ticket-linked "
                    "cancellation order whose location-only count, contract label, "
                    "location IDs, or subscription grouping was not exact"
                )
            matched_subscriptions.add(subscription_id)
            matched_orders.append(order)
        if not matched_orders:
            raise SalesforceScopeError(
                "Account cancellation confirmation requires at least one exact "
                "ticket-linked cancellation order with Maxio location-component evidence"
            )

        account_name = str(account.get("Name") or "").strip() or "your NOVA POS account"
        targets = self._billing_confirmation_targets(ticket)
        render_contact_id = self._account_cancellation_render_contact(
            clean_account_id,
            clean_ticket_id,
            targets.get("renderContactId") or "",
        )
        if render_contact_id:
            targets = dict(targets)
            targets["renderContactId"] = render_contact_id
        template = self._resolve_approved_email_template(
            "account_cancellation_confirmed",
            lane="billing_agent",
            allow_specialized=True,
        )
        sender = self._resolve_department_sender("billing")
        preview = self._render_stored_email_template(
            template_id=template["templateId"],
            recipient_id=targets["renderContactId"],
            related_record_id=clean_ticket_id,
        )
        preview = _normalize_agent_email_signature(preview, department="billing")
        preview_summary = _verify_approved_template_preview(
            preview,
            expected_subject=template["subject"],
            brand_template_id=template["brandTemplateId"],
            required_fragments=[account_name, ticket_number],
        )
        prepared = {
            "ticketId": clean_ticket_id,
            "situation": "account_cancellation_confirmed",
            "templateId": template["templateId"],
            "templateName": template["templateName"],
            "templateDeveloperName": template["templateDeveloperName"],
            "subject": template["subject"],
            "brandTemplateId": template["brandTemplateId"],
            "renderedPreview": preview,
            "previewSummary": preview_summary,
            "targets": targets,
            "sender": sender,
            "requiredFragments": [account_name, ticket_number],
            "customized": False,
        }
        idempotency_key, target, plan_hash = _ticket_template_delivery_identity(
            prepared,
            key_prefix="account-cancellation-confirmation-email",
        )
        operation = "salesforce_account_cancellation_confirmation_email_send"
        with self._salesforce_operation(
            idempotency_key,
            operation,
            target,
            plan_hash,
            track_provider_attempt=True,
            reconcile_pending=lambda: self._reconcile_approved_ticket_template_delivery(
                prepared
            ),
        ) as prior:
            if prior is not None:
                delivery = {
                    **prior,
                    "sent": False,
                    "duplicate": True,
                    "replayed": True,
                    "writesPerformed": False,
                    "providerResult": None,
                    "idempotencyKey": idempotency_key,
                }
            else:
                delivery = {
                    **self._deliver_approved_ticket_template(
                        prepared,
                        mark_provider_attempt=lambda: self._mark_salesforce_provider_attempt(
                            idempotency_key,
                            operation,
                            target,
                            plan_hash,
                        ),
                    ),
                    "replayed": False,
                    "idempotencyKey": idempotency_key,
                }
                delivery["writesPerformed"] = bool(delivery.get("sent"))
                self._complete_salesforce_operation(
                    idempotency_key,
                    operation,
                    target,
                    plan_hash,
                    delivery,
                )
        return {
            **delivery,
            "ticketNumber": ticket_number,
            "accountName": account_name,
            "subject": template["subject"],
            "templateId": template["templateId"],
            "templateName": template["templateName"],
            "templateDeveloperName": template["templateDeveloperName"],
            "templatePreview": preview_summary,
            "accountStateVerified": True,
            "activeLocationCount": 0,
            "cancellationOrderId": str(matched_orders[0].get("Id") or ""),
            "cancellationOrderIds": [
                str(order.get("Id") or "") for order in matched_orders
            ],
            "cancellationOrderCount": len(matched_orders),
            "oneOrderPerSubscriptionVerified": True,
            "callerSelectedRecipients": False,
            "callerSelectedContent": False,
            "callerSelectedTemplate": False,
        }

    def read_billing_account(self, account_id: str) -> dict[str, Any]:
        """Read the exact Account billing-rate fields needed for component selection."""

        clean_id = _required_id(account_id, "account_id")
        result = self._query(
            "SELECT Id,Name,Company_Username__c,Nova_ID__c,Fake_Account__c,Flat_Rate_Amount__c,"
            "Monthly_Revenue_per_Location__c,Base_Location_Price__c,Payments_Partner__c,"
            "NovaPOS_Active__c,Status__c,Real_Account_Status__c,OwnerId,Nova_Account_Manager__c "
            f"FROM Account WHERE Id = '{clean_id}' LIMIT 1"
        )
        records = [record for record in result.get("records", []) if isinstance(record, dict)]
        if len(records) != 1:
            raise SalesforceScopeError("account_id did not resolve to exactly one Salesforce Account")
        record = dict(records[0])
        record.pop("attributes", None)
        return {"ok": True, "record": record}

    def update_billing_account_flat_rate(
        self,
        account_id: str,
        monthly_rate_cents: int,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Update only Account.Flat_Rate_Amount__c and verify the exact amount by readback."""

        clean_id = _required_id(account_id, "account_id")
        clean_key = str(idempotency_key or "").strip()
        if not IDEMPOTENCY_KEY.fullmatch(clean_key):
            raise SalesforceScopeError("idempotency_key must contain 8-240 safe characters")
        try:
            clean_cents = int(monthly_rate_cents)
        except (TypeError, ValueError) as exc:
            raise SalesforceScopeError("monthly_rate_cents must be an integer") from exc
        if isinstance(monthly_rate_cents, bool) or clean_cents < 0 or clean_cents > 10_000_000:
            raise SalesforceScopeError("monthly_rate_cents must be between 0 and 10000000")

        before = self.read_billing_account(clean_id)["record"]
        before_cents = _decimal_currency_field_to_cents(before.get("Flat_Rate_Amount__c"))
        if before_cents == clean_cents:
            return {
                "ok": True,
                "updated": False,
                "duplicate": True,
                "verified": True,
                "id": clean_id,
                "idempotencyKey": clean_key,
                "field": "Flat_Rate_Amount__c",
                "monthlyRateCents": clean_cents,
                "before": before,
                "readback": before,
            }

        desired_amount = float((Decimal(clean_cents) / Decimal(100)).quantize(Decimal("0.01")))
        self._request(
            "PATCH",
            f"/sobjects/Account/{clean_id}",
            json={"Flat_Rate_Amount__c": desired_amount},
        )
        readback = self.read_billing_account(clean_id)["record"]
        readback_cents = _decimal_currency_field_to_cents(readback.get("Flat_Rate_Amount__c"))
        if readback_cents != clean_cents:
            raise SalesforceUnavailableError(
                "Salesforce Account flat-rate readback did not match; do not retry until the record is read again"
            )
        return {
            "ok": True,
            "updated": True,
            "duplicate": False,
            "verified": True,
            "id": clean_id,
            "idempotencyKey": clean_key,
            "field": "Flat_Rate_Amount__c",
            "monthlyRateCents": clean_cents,
            "before": before,
            "readback": readback,
        }

    def clear_billing_account_flat_rate(
        self,
        account_id: str,
        expected_current_rate_cents: int,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Clear only an exact, expected Account flat rate and verify a null readback."""

        clean_id = _required_id(account_id, "account_id")
        clean_key = _required_idempotency_key(idempotency_key)
        clean_expected = _required_positive_cents(
            expected_current_rate_cents,
            "expected_current_rate_cents",
        )
        before = self.read_billing_account(clean_id)["record"]
        before_cents = _decimal_currency_field_to_cents(before.get("Flat_Rate_Amount__c"))
        if before_cents is None:
            return {
                "ok": True,
                "updated": False,
                "duplicate": True,
                "verified": True,
                "id": clean_id,
                "idempotencyKey": clean_key,
                "field": "Flat_Rate_Amount__c",
                "expectedCurrentRateCents": clean_expected,
                "before": before,
                "readback": before,
            }
        if before_cents != clean_expected:
            raise SalesforceScopeError(
                "Account flat rate no longer matches expected_current_rate_cents; read the Account again"
            )
        plan = {
            "operation": "salesforce_billing_account_flat_rate_clear",
            "accountId": clean_id,
            "expectedCurrentRateCents": clean_expected,
            "desired": {"Flat_Rate_Amount__c": None},
        }
        plan_hash = _stable_plan_hash(plan)
        operation = "billing_account_flat_rate_clear"
        with self._salesforce_operation(
            clean_key,
            operation,
            clean_id,
            plan_hash,
            track_provider_attempt=True,
        ) as prior:
            if prior is not None:
                return {**prior, "duplicate": True, "idempotencyKey": clean_key}
            self._mark_salesforce_provider_attempt(
                clean_key,
                operation,
                clean_id,
                plan_hash,
                evidence={"expectedCurrentRateCents": clean_expected},
            )
            self._request(
                "PATCH",
                f"/sobjects/Account/{clean_id}",
                json={"Flat_Rate_Amount__c": None},
            )
            readback = self.read_billing_account(clean_id)["record"]
            if _decimal_currency_field_to_cents(readback.get("Flat_Rate_Amount__c")) is not None:
                raise SalesforceUnavailableError(
                    "Salesforce Account flat-rate clear did not read back null; do not retry"
                )
            result = {
                "ok": True,
                "updated": True,
                "duplicate": False,
                "verified": True,
                "id": clean_id,
                "idempotencyKey": clean_key,
                "field": "Flat_Rate_Amount__c",
                "expectedCurrentRateCents": clean_expected,
                "before": before,
                "readback": readback,
            }
            self._complete_salesforce_operation(
                clean_key,
                operation,
                clean_id,
                plan_hash,
                result,
            )
            return result

    def update_billing_location_gateway(
        self,
        location_id: str,
        integrated: bool,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Set one location's integrated-gateway flag with exact readback."""

        clean_id = _required_id(location_id, "location_id")
        clean_key = _required_idempotency_key(idempotency_key)
        if not isinstance(integrated, bool):
            raise SalesforceScopeError("integrated must be true or false")
        records = self.lookup("location", clean_id, limit=1)["records"]
        if len(records) != 1:
            raise SalesforceScopeError(
                "location_id did not resolve to exactly one Salesforce location"
            )
        before = dict(records[0])
        current = before.get("Is_Location_on_GSPayTech_Gateway__c") is True
        if current is integrated:
            return {
                "ok": True,
                "updated": False,
                "duplicate": True,
                "verified": True,
                "id": clean_id,
                "idempotencyKey": clean_key,
                "field": "Is_Location_on_GSPayTech_Gateway__c",
                "integrated": integrated,
                "before": before,
                "readback": before,
            }
        plan = {
            "operation": "salesforce_billing_location_gateway_update",
            "locationId": clean_id,
            "before": current,
            "desired": integrated,
        }
        plan_hash = _stable_plan_hash(plan)
        operation = "billing_location_gateway_update"
        with self._salesforce_operation(
            clean_key,
            operation,
            clean_id,
            plan_hash,
            track_provider_attempt=True,
        ) as prior:
            if prior is not None:
                return {**prior, "duplicate": True, "idempotencyKey": clean_key}
            self._mark_salesforce_provider_attempt(
                clean_key,
                operation,
                clean_id,
                plan_hash,
                evidence={"before": current, "desired": integrated},
            )
            self._request(
                "PATCH",
                f"/sobjects/NovaPOS_Location__c/{clean_id}",
                json={"Is_Location_on_GSPayTech_Gateway__c": integrated},
            )
            readback_records = self.lookup("location", clean_id, limit=1)["records"]
            if len(readback_records) != 1:
                raise SalesforceUnavailableError(
                    "Salesforce location gateway readback was unavailable; do not retry"
                )
            readback = dict(readback_records[0])
            if (readback.get("Is_Location_on_GSPayTech_Gateway__c") is True) is not integrated:
                raise SalesforceUnavailableError(
                    "Salesforce location gateway readback did not match; do not retry"
                )
            result = {
                "ok": True,
                "updated": True,
                "duplicate": False,
                "verified": True,
                "id": clean_id,
                "idempotencyKey": clean_key,
                "field": "Is_Location_on_GSPayTech_Gateway__c",
                "integrated": integrated,
                "before": before,
                "readback": readback,
            }
            self._complete_salesforce_operation(
                clean_key,
                operation,
                clean_id,
                plan_hash,
                result,
            )
            return result

    def account_fake_classification_preview(
        self,
        ticket_id: str,
        account_id: str,
        nova_id: str,
        *,
        is_fake: bool,
    ) -> dict[str, Any]:
        """Preview the exact Account.Fake_Account__c classification behind one Billing ticket."""

        clean_account_id = _required_id(account_id, "account_id")
        clean_nova_id = str(nova_id or "").strip().upper()
        if not NOVA_ID.fullmatch(clean_nova_id):
            raise SalesforceScopeError("nova_id must be an exact value such as A-123456")
        if not isinstance(is_fake, bool):
            raise SalesforceScopeError("is_fake must be true or false")
        ticket = self._assert_billing_ticket_account(ticket_id, clean_account_id)
        account = self.read_billing_account(clean_account_id)["record"]
        if str(account.get("Nova_ID__c") or "").strip().upper() != clean_nova_id:
            raise SalesforceScopeError("nova_id does not match the exact Salesforce Account")
        before_value = bool(account.get("Fake_Account__c"))
        plan = {
            "operation": "salesforce_account_fake_classification",
            "ticketId": str(ticket.get("Id") or ticket_id),
            "ticketNumber": str(ticket.get("Name") or ""),
            "accountId": clean_account_id,
            "novaId": clean_nova_id,
            "accountName": str(account.get("Name") or ""),
            "before": {"Fake_Account__c": before_value},
            "desired": {"Fake_Account__c": is_fake},
            "duplicate": before_value is is_fake,
        }
        return {
            "ok": True,
            "status": "preview",
            "verified": True,
            **plan,
            "planHash": _stable_plan_hash(plan),
            "writesPerformed": False,
        }

    def apply_account_fake_classification(
        self,
        ticket_id: str,
        account_id: str,
        nova_id: str,
        *,
        is_fake: bool,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Apply one unchanged fake/real classification and verify the exact Account field."""

        clean_key = _required_idempotency_key(idempotency_key)
        clean_hash = _required_preview_hash(preview_hash)
        preview = self.account_fake_classification_preview(
            ticket_id,
            account_id,
            nova_id,
            is_fake=is_fake,
        )
        if preview["planHash"] != clean_hash:
            raise SalesforceScopeError("preview_hash does not match the current fake-account plan")
        if preview["duplicate"]:
            return {
                **preview,
                "status": "completed",
                "updated": False,
                "duplicate": True,
                "idempotencyKey": clean_key,
                "readback": preview["before"],
            }
        with self._salesforce_operation(
            clean_key,
            "account_fake_classification",
            preview["accountId"],
            clean_hash,
        ) as prior:
            if prior is not None:
                return {**prior, "duplicate": True, "idempotencyKey": clean_key}
            self._request(
                "PATCH",
                f"/sobjects/Account/{preview['accountId']}",
                json=dict(preview["desired"]),
            )
            readback = self.read_billing_account(preview["accountId"])["record"]
            if bool(readback.get("Fake_Account__c")) is not bool(is_fake):
                raise SalesforceUnavailableError(
                    "Salesforce fake-account readback did not match; do not retry until the Account is read again"
                )
            result = {
                **preview,
                "status": "completed",
                "updated": True,
                "duplicate": False,
                "verified": True,
                "idempotencyKey": clean_key,
                "readback": readback,
            }
            self._complete_salesforce_operation(
                clean_key,
                "account_fake_classification",
                preview["accountId"],
                clean_hash,
                result,
            )
            return result

    def billing_schedule_date_preview(
        self,
        ticket_id: str,
        account_id: str,
        billing_schedule_id: str,
        subscription_id: int,
        start_date: str,
    ) -> dict[str, Any]:
        """Preview changing only one verified Billing Schedule start date."""

        clean_account_id = _required_id(account_id, "account_id")
        clean_schedule_id = _required_id(billing_schedule_id, "billing_schedule_id")
        clean_subscription_id = _positive_salesforce_external_id(
            subscription_id,
            "subscription_id",
        )
        clean_start_date = _salesforce_date(start_date, "start_date")
        ticket = self._assert_operational_ticket_account(ticket_id, clean_account_id)
        schedule = self._read_billing_schedule(clean_schedule_id)
        if str(schedule.get("Account__c") or "") != clean_account_id:
            raise SalesforceScopeError(
                "billing_schedule_id does not belong to the requested Salesforce Account"
            )
        schedule_subscription_ids = {
            _numeric_identifier(schedule.get("Chargify_Subscription_ID__c")),
            _numeric_identifier(schedule.get("Billing_Circle_Schedule_ID__c")),
        }
        if schedule_subscription_ids != {clean_subscription_id}:
            raise SalesforceScopeError(
                "billing_schedule_id does not have both exact identifiers for subscription_id"
            )
        before = {"Start_Date__c": schedule.get("Start_Date__c")}
        desired = {"Start_Date__c": clean_start_date}
        plan = {
            "operation": "salesforce_billing_schedule_date",
            "ticketId": str(ticket.get("Id") or ticket_id),
            "ticketNumber": str(ticket.get("Name") or ""),
            "accountId": clean_account_id,
            "billingScheduleId": clean_schedule_id,
            "subscriptionId": clean_subscription_id,
            "before": before,
            "desired": desired,
            "duplicate": _salesforce_field_matches(
                before["Start_Date__c"],
                clean_start_date,
                "Start_Date__c",
            ),
        }
        return {
            "ok": True,
            "status": "preview",
            "verified": True,
            **plan,
            "planHash": _stable_plan_hash(plan),
            "writesPerformed": False,
        }

    def apply_billing_schedule_date(
        self,
        ticket_id: str,
        account_id: str,
        billing_schedule_id: str,
        subscription_id: int,
        start_date: str,
        *,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Apply one unchanged date-only Billing Schedule plan and verify it."""

        clean_key = _required_idempotency_key(idempotency_key)
        clean_hash = _required_preview_hash(preview_hash)
        preview = self.billing_schedule_date_preview(
            ticket_id,
            account_id,
            billing_schedule_id,
            subscription_id,
            start_date,
        )
        if preview["planHash"] != clean_hash:
            raise SalesforceScopeError(
                "preview_hash does not match the current Billing Schedule date plan"
            )
        if preview["duplicate"]:
            return {
                **preview,
                "status": "completed",
                "updated": False,
                "duplicate": True,
                "idempotencyKey": clean_key,
                "readback": preview["before"],
            }
        operation = "billing_schedule_date"
        with self._salesforce_operation(
            clean_key,
            operation,
            preview["billingScheduleId"],
            clean_hash,
            track_provider_attempt=True,
        ) as prior:
            if prior is not None:
                return {**prior, "duplicate": True, "idempotencyKey": clean_key}
            self._mark_salesforce_provider_attempt(
                clean_key,
                operation,
                preview["billingScheduleId"],
                clean_hash,
                evidence={
                    "subscriptionId": preview["subscriptionId"],
                    "before": preview["before"],
                    "desired": preview["desired"],
                },
            )
            self._request(
                "PATCH",
                "/sobjects/NovaPOS_Billing_Schedule__c/"
                f"{preview['billingScheduleId']}",
                json=dict(preview["desired"]),
            )
            readback = self._read_billing_schedule(preview["billingScheduleId"])
            if not _salesforce_field_matches(
                readback.get("Start_Date__c"),
                preview["desired"]["Start_Date__c"],
                "Start_Date__c",
            ):
                raise SalesforceUnavailableError(
                    "Salesforce Billing Schedule date readback did not match; do not retry"
                )
            result = {
                **preview,
                "status": "completed",
                "updated": True,
                "duplicate": False,
                "verified": True,
                "idempotencyKey": clean_key,
                "readback": _bounded_record(readback),
            }
            self._complete_salesforce_operation(
                clean_key,
                operation,
                preview["billingScheduleId"],
                clean_hash,
                result,
            )
            return result

    def billing_location_alignment_preview(
        self,
        ticket_id: str,
        account_id: str,
        location_id: str,
        nova_location_id: int,
        *,
        desired_status: str,
        monthly_rate_cents: int | None = None,
        chargify_subscription_id: int | None = None,
        billing_schedule_id: str = "",
        clear_subscription_link: bool = False,
        clear_schedule_link: bool = False,
        billing_exception: str = "",
    ) -> dict[str, Any]:
        """Preview a bounded lifecycle/rate/subscription-link repair for one exact location."""

        clean_account_id = _required_id(account_id, "account_id")
        clean_location_id = _required_id(location_id, "location_id")
        self._assert_operational_ticket_account(ticket_id, clean_account_id)
        try:
            clean_nova_location_id = int(nova_location_id)
        except (TypeError, ValueError) as exc:
            raise SalesforceScopeError("nova_location_id must be a positive integer") from exc
        if isinstance(nova_location_id, bool) or clean_nova_location_id <= 0:
            raise SalesforceScopeError("nova_location_id must be a positive integer")
        status_key = str(desired_status or "").strip().casefold()
        if status_key not in LOCATION_STATUS_VALUES:
            raise SalesforceScopeError("desired_status must be Active, Inactive, or Storage")
        clean_status = LOCATION_STATUS_VALUES[status_key]
        if monthly_rate_cents is None:
            clean_rate_cents = None
        else:
            try:
                clean_rate_cents = int(monthly_rate_cents)
            except (TypeError, ValueError) as exc:
                raise SalesforceScopeError("monthly_rate_cents must be an integer") from exc
            if (
                isinstance(monthly_rate_cents, bool)
                or clean_rate_cents < 0
                or clean_rate_cents > 10_000_000
            ):
                raise SalesforceScopeError("monthly_rate_cents must be between 0 and 10000000")
        if clear_subscription_link and chargify_subscription_id is not None:
            raise SalesforceScopeError(
                "clear_subscription_link cannot be combined with chargify_subscription_id"
            )
        clean_subscription_id: int | None = None
        if chargify_subscription_id is not None:
            try:
                clean_subscription_id = int(chargify_subscription_id)
            except (TypeError, ValueError) as exc:
                raise SalesforceScopeError("chargify_subscription_id must be a positive integer") from exc
            if isinstance(chargify_subscription_id, bool) or clean_subscription_id <= 0:
                raise SalesforceScopeError("chargify_subscription_id must be a positive integer")
        if clear_schedule_link and str(billing_schedule_id or "").strip():
            raise SalesforceScopeError("clear_schedule_link cannot be combined with billing_schedule_id")
        clean_schedule_id = _optional_id(billing_schedule_id, "billing_schedule_id")
        clean_exception = str(billing_exception or "").strip().casefold()
        if clean_exception not in {"", "intentional_free"}:
            raise SalesforceScopeError("billing_exception may only be intentional_free")

        before_records = self.lookup("location", clean_location_id, limit=1)["records"]
        if len(before_records) != 1:
            raise SalesforceScopeError("location_id did not resolve to exactly one Salesforce location")
        before = dict(before_records[0])
        if str(before.get("Account__c") or "") != clean_account_id:
            raise SalesforceScopeError("location_id does not belong to the Billing ticket Account")
        if _normalized_location_id(before.get("Location_ID__c")) != str(clean_nova_location_id):
            raise SalesforceScopeError(
                "nova_location_id does not match the exact Salesforce location"
            )

        desired: dict[str, Any] = {"Status__c": clean_status}
        if clean_status == "Inactive":
            # Clear this obsolete workflow predicate before the lifecycle write. The
            # legacy Salesforce process otherwise creates a Billing ticket with a
            # retired restricted-picklist value and rolls the whole transaction back.
            desired["Is_Location_on_GSPayTech_Gateway__c"] = False
        if clean_rate_cents is not None:
            desired["Bill_Amount__c"] = float(
                (Decimal(clean_rate_cents) / Decimal(100)).quantize(Decimal("0.01"))
            )
        if clean_subscription_id is not None:
            desired["Chargify_Subscription_ID__c"] = str(clean_subscription_id)
        elif clear_subscription_link:
            desired["Chargify_Subscription_ID__c"] = None
        if clean_schedule_id:
            schedule = self._read_billing_schedule(clean_schedule_id)
            if str(schedule.get("Account__c") or "") != clean_account_id:
                raise SalesforceScopeError(
                    "billing_schedule_id does not belong to the requested Salesforce Account"
                )
            desired["NovaPOS_Billing_Schedule__c"] = clean_schedule_id
        elif clear_schedule_link:
            desired["NovaPOS_Billing_Schedule__c"] = None

        resulting_subscription = (
            desired.get("Chargify_Subscription_ID__c")
            if "Chargify_Subscription_ID__c" in desired
            else before.get("Chargify_Subscription_ID__c")
        )
        resulting_rate_cents = (
            clean_rate_cents
            if clean_rate_cents is not None
            else _decimal_currency_field_to_cents(before.get("Bill_Amount__c"))
        )
        if clean_status == "Active" and not str(resulting_subscription or "").strip():
            if clean_exception != "intentional_free" or resulting_rate_cents not in {None, 0}:
                raise SalesforceScopeError(
                    "an Active location without a Maxio subscription requires billing_exception=intentional_free "
                    "and a zero or empty Salesforce rate"
                )

        comparable_before = {
            "Status__c": before.get("Status__c"),
            "Bill_Amount__c": before.get("Bill_Amount__c"),
            "Chargify_Subscription_ID__c": before.get("Chargify_Subscription_ID__c"),
            "NovaPOS_Billing_Schedule__c": before.get("NovaPOS_Billing_Schedule__c"),
            "Is_Location_on_GSPayTech_Gateway__c": before.get(
                "Is_Location_on_GSPayTech_Gateway__c"
            ),
        }
        duplicate = all(
            _salesforce_field_matches(comparable_before.get(field), value, field)
            for field, value in desired.items()
        )
        staged_changes: list[dict[str, Any]] = []
        link_changes = {
            field: desired[field]
            for field in ("Chargify_Subscription_ID__c", "NovaPOS_Billing_Schedule__c")
            if field in desired
            and not _salesforce_field_matches(comparable_before.get(field), desired[field], field)
        }
        if clean_status == "Inactive":
            deactivation_guard_changes = {
                field: desired[field]
                for field in (
                    "Is_Location_on_GSPayTech_Gateway__c",
                    "Chargify_Subscription_ID__c",
                    "NovaPOS_Billing_Schedule__c",
                )
                if field in desired
                and not _salesforce_field_matches(
                    comparable_before.get(field), desired[field], field
                )
            }
            if deactivation_guard_changes:
                staged_changes.append(
                    {
                        "name": "deactivation_guards",
                        "desired": deactivation_guard_changes,
                    }
                )
                for field in deactivation_guard_changes:
                    link_changes.pop(field, None)
        lifecycle_changes = {
            field: desired[field]
            for field in ("Status__c", "Bill_Amount__c")
            if field in desired
            and not _salesforce_field_matches(comparable_before.get(field), desired[field], field)
        }
        if lifecycle_changes:
            staged_changes.append(
                {
                    "name": "lifecycle",
                    "desired": lifecycle_changes,
                }
            )
        if link_changes:
            staged_changes.append(
                {
                    "name": "billing_links",
                    "desired": link_changes,
                }
            )
        plan = {
            "operation": "salesforce_billing_location_alignment",
            "ticketId": _required_id(ticket_id, "ticket_id"),
            "accountId": clean_account_id,
            "locationId": clean_location_id,
            "novaLocationId": clean_nova_location_id,
            "billingException": clean_exception,
            "before": comparable_before,
            "desired": desired,
            "stagedChanges": staged_changes,
            "duplicate": duplicate,
        }
        return {
            "ok": True,
            "status": "preview",
            "verified": True,
            **plan,
            "planHash": _stable_plan_hash(plan),
            "writesPerformed": False,
        }

    def apply_billing_location_alignment(
        self,
        ticket_id: str,
        account_id: str,
        location_id: str,
        nova_location_id: int,
        *,
        desired_status: str,
        monthly_rate_cents: int | None = None,
        chargify_subscription_id: int | None = None,
        billing_schedule_id: str = "",
        clear_subscription_link: bool = False,
        clear_schedule_link: bool = False,
        billing_exception: str = "",
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Apply one unchanged location alignment plan and verify every requested field."""

        clean_key = _required_idempotency_key(idempotency_key)
        clean_hash = _required_preview_hash(preview_hash)
        preview = self.billing_location_alignment_preview(
            ticket_id,
            account_id,
            location_id,
            nova_location_id,
            desired_status=desired_status,
            monthly_rate_cents=monthly_rate_cents,
            chargify_subscription_id=chargify_subscription_id,
            billing_schedule_id=billing_schedule_id,
            clear_subscription_link=clear_subscription_link,
            clear_schedule_link=clear_schedule_link,
            billing_exception=billing_exception,
        )
        if preview["planHash"] != clean_hash:
            raise SalesforceScopeError("preview_hash does not match the current location-alignment plan")
        if preview["duplicate"]:
            return {
                **preview,
                "status": "completed",
                "updated": False,
                "duplicate": True,
                "idempotencyKey": clean_key,
                "readback": preview["before"],
            }
        with self._salesforce_operation(
            clean_key,
            "billing_location_alignment",
            preview["locationId"],
            clean_hash,
        ) as prior:
            if prior is not None:
                return {**prior, "duplicate": True, "idempotencyKey": clean_key}
            completed_stages: list[str] = []
            for stage in preview["stagedChanges"]:
                current_records = self.lookup(
                    "location",
                    preview["locationId"],
                    limit=1,
                )["records"]
                if len(current_records) != 1:
                    raise SalesforceUnavailableError(
                        "Salesforce location alignment stage readback was unavailable; do not retry"
                    )
                current = dict(current_records[0])
                remaining = {
                    field: value
                    for field, value in stage["desired"].items()
                    if not _salesforce_field_matches(current.get(field), value, field)
                }
                if not remaining:
                    completed_stages.append(stage["name"])
                    continue
                try:
                    self._request(
                        "PATCH",
                        f"/sobjects/NovaPOS_Location__c/{preview['locationId']}",
                        json=remaining,
                    )
                except SalesforceUnavailableError as exc:
                    raise SalesforceUnavailableError(
                        f"Salesforce location alignment {stage['name']} stage failed: {exc}"
                    ) from exc
                stage_records = self.lookup(
                    "location",
                    preview["locationId"],
                    limit=1,
                )["records"]
                if len(stage_records) != 1 or any(
                    not _salesforce_field_matches(
                        dict(stage_records[0]).get(field),
                        value,
                        field,
                    )
                    for field, value in remaining.items()
                ):
                    raise SalesforceUnavailableError(
                        f"Salesforce location alignment {stage['name']} stage readback did not match; "
                        "do not retry until the location is read again"
                    )
                completed_stages.append(stage["name"])
            records = self.lookup("location", preview["locationId"], limit=1)["records"]
            if len(records) != 1:
                raise SalesforceUnavailableError(
                    "Salesforce location alignment readback was unavailable; do not retry"
                )
            readback = dict(records[0])
            if not all(
                _salesforce_field_matches(readback.get(field), value, field)
                for field, value in preview["desired"].items()
            ):
                raise SalesforceUnavailableError(
                    "Salesforce location alignment readback did not match; "
                    "do not retry until the location is read again"
                )
            result = {
                **preview,
                "status": "completed",
                "updated": True,
                "duplicate": False,
                "verified": True,
                "idempotencyKey": clean_key,
                "completedStages": completed_stages,
                "readback": readback,
            }
            self._complete_salesforce_operation(
                clean_key,
                "billing_location_alignment",
                preview["locationId"],
                clean_hash,
                result,
            )
            return result

    def read_billing_structure(self, account_id: str) -> dict[str, Any]:
        """Read bounded Billing Account and Billing Schedule rows for one Account."""

        clean_account_id = _required_id(account_id, "account_id")
        optional_billing_fields_available = True
        try:
            account_result = self._query(
                "SELECT Id,Name,Account__c,Billing_Circle_Client_ID__c,"
                "Chargify_Payment_Profile_ID__c,Status__c,Active_Schedule__c,CreatedDate "
                "FROM NovaPOS_Billing_Account__c "
                f"WHERE Account__c = '{clean_account_id}' ORDER BY CreatedDate,Id LIMIT 200"
            )
        except SalesforceUnavailableError:
            # Older Salesforce orgs or restricted field-level security may not expose
            # Rainfall's optional payment-profile and active-schedule helper fields.
            # Their absence must not block creation of the core Billing Account,
            # Billing Schedule, and exact location-to-schedule links.
            account_result = self._query(
                "SELECT Id,Name,Account__c,Billing_Circle_Client_ID__c,Status__c,CreatedDate "
                "FROM NovaPOS_Billing_Account__c "
                f"WHERE Account__c = '{clean_account_id}' ORDER BY CreatedDate,Id LIMIT 200"
            )
            optional_billing_fields_available = False
        billing_accounts = [
            _bounded_record(record)
            for record in account_result.get("records", [])
            if isinstance(record, dict)
        ]
        schedule_result = self._query(
            "SELECT Id,Name,NovaPOS_Billing_Account__c,"
            "NovaPOS_Billing_Account__r.Account__c,Title__c,Schedule_Interval__c,"
            "Bill_Amount__c,Start_Date__c,Billing_Circle_Schedule_ID__c,"
            "Chargify_Subscription_ID__c,Type__c,CreatedDate "
            "FROM NovaPOS_Billing_Schedule__c "
            f"WHERE NovaPOS_Billing_Account__r.Account__c = '{clean_account_id}' "
            "ORDER BY CreatedDate,Id LIMIT 500"
        )
        schedules: list[dict[str, Any]] = []
        for raw in schedule_result.get("records", []):
            if not isinstance(raw, dict):
                continue
            record = dict(raw)
            related = (
                record.pop("NovaPOS_Billing_Account__r", None)
                if isinstance(record.get("NovaPOS_Billing_Account__r"), dict)
                else None
            )
            record["Account__c"] = str((related or {}).get("Account__c") or "")
            schedules.append(_bounded_record(record))
        return {
            "ok": True,
            "accountId": clean_account_id,
            "billingAccounts": billing_accounts,
            "billingSchedules": schedules,
            "counts": {
                "billingAccounts": len(billing_accounts),
                "billingSchedules": len(schedules),
            },
            "optionalBillingFieldsAvailable": optional_billing_fields_available,
            "readOnly": True,
            "writesPerformed": False,
        }

    def billing_structure_alignment_preview(
        self,
        ticket_id: str,
        account_id: str,
        *,
        maxio_customer_id: int,
        payment_profile_id: int | None,
        subscription_id: int,
        subscription_state: str,
        bill_amount_cents: int,
        start_date: str,
        nova_location_ids: list[int],
        salesforce_location_ids: list[str] | None = None,
        billing_account_id: str = "",
        billing_schedule_id: str = "",
    ) -> dict[str, Any]:
        """Preview idempotent Salesforce billing bookkeeping for one verified Maxio subscription."""

        clean_account_id = _required_id(account_id, "account_id")
        ticket = self._assert_operational_ticket_account(ticket_id, clean_account_id)
        clean_customer_id = _positive_salesforce_external_id(maxio_customer_id, "maxio_customer_id")
        clean_profile_id = (
            _positive_salesforce_external_id(payment_profile_id, "payment_profile_id")
            if payment_profile_id is not None
            else None
        )
        clean_subscription_id = _positive_salesforce_external_id(subscription_id, "subscription_id")
        clean_state = str(subscription_state or "").strip().casefold()
        if clean_state not in {"active", "trial", "trialing", "awaiting_signup"}:
            raise SalesforceScopeError(
                "subscription_state must be active, trial, trialing, or awaiting_signup"
            )
        clean_bill_cents = _nonnegative_cents(bill_amount_cents, "bill_amount_cents")
        clean_start_date = _salesforce_date(start_date, "start_date")
        clean_location_ids = _unique_positive_ids(nova_location_ids, "nova_location_ids", limit=500)
        if not clean_location_ids:
            raise SalesforceScopeError("nova_location_ids must contain at least one exact location")
        clean_salesforce_location_ids = _unique_salesforce_record_ids(
            salesforce_location_ids,
            "salesforce_location_ids",
            limit=500,
        )
        clean_billing_account_id = _optional_id(
            billing_account_id,
            "billing_account_id",
        )
        clean_billing_schedule_id = _optional_id(
            billing_schedule_id,
            "billing_schedule_id",
        )
        if bool(clean_billing_account_id) != bool(clean_billing_schedule_id):
            raise SalesforceScopeError(
                "billing_account_id and billing_schedule_id must be supplied together"
            )
        account = self.read_billing_account(clean_account_id)["record"]
        structure = self.read_billing_structure(clean_account_id)
        if structure["optionalBillingFieldsAvailable"] and clean_profile_id is None:
            raise SalesforceScopeError(
                "payment_profile_id is required when Salesforce exposes the payment-profile field"
            )
        billing_accounts = list(structure["billingAccounts"])
        customer_matches = [
            row
            for row in billing_accounts
            if _numeric_identifier(row.get("Billing_Circle_Client_ID__c")) == clean_customer_id
        ]
        subscription_matches = [
            row
            for row in structure["billingSchedules"]
            if clean_subscription_id
            in {
                _numeric_identifier(row.get("Chargify_Subscription_ID__c")),
                _numeric_identifier(row.get("Billing_Circle_Schedule_ID__c")),
            }
        ]
        if len(subscription_matches) > 1:
            raise SalesforceScopeError(
                "multiple Salesforce Billing Schedules match the Maxio subscription; resolve duplicates first"
            )
        schedule = subscription_matches[0] if subscription_matches else None
        if clean_billing_schedule_id:
            if schedule is None or str(schedule.get("Id") or "") != clean_billing_schedule_id:
                raise SalesforceScopeError(
                    "billing_schedule_id must select the one exact schedule for subscription_id"
                )
        billing_accounts_by_id = {
            str(row.get("Id") or ""): row
            for row in billing_accounts
            if str(row.get("Id") or "")
        }
        schedule_parent = (
            billing_accounts_by_id.get(str(schedule.get("NovaPOS_Billing_Account__c") or ""))
            if schedule
            else None
        )
        if schedule and schedule_parent is None:
            raise SalesforceScopeError(
                "the matching Billing Schedule parent did not resolve under the exact Account"
            )
        if clean_billing_account_id:
            selected_billing_account = billing_accounts_by_id.get(clean_billing_account_id)
            if selected_billing_account is None:
                raise SalesforceScopeError(
                    "billing_account_id did not resolve under the exact Salesforce Account"
                )
            if schedule_parent is not None and str(schedule_parent.get("Id") or "") != clean_billing_account_id:
                raise SalesforceScopeError(
                    "billing_account_id must select the exact parent of billing_schedule_id"
                )
        else:
            selected_billing_account = None
        # NovaPOS_Billing_Schedule__c.NovaPOS_Billing_Account__c is create-only
        # in production. An existing subscription schedule therefore makes its
        # current parent the canonical Billing Account to synchronize in place.
        if schedule_parent is not None:
            billing_account = schedule_parent
        elif selected_billing_account is not None:
            if customer_matches and all(
                str(row.get("Id") or "") != clean_billing_account_id
                for row in customer_matches
            ):
                raise SalesforceScopeError(
                    "billing_account_id does not match the verified Maxio customer"
                )
            billing_account = selected_billing_account
        else:
            if len(customer_matches) > 1:
                raise SalesforceScopeError(
                    "multiple Salesforce Billing Accounts match the Maxio customer; resolve duplicates first"
                )
            billing_account = customer_matches[0] if customer_matches else None
        desired_billing_account: dict[str, Any] = {
            "Account__c": clean_account_id,
            "Name": f"{str(account.get('Name') or 'Account').strip()} {clean_subscription_id}"[:80],
            "Status__c": "Active",
        }
        if structure["optionalBillingFieldsAvailable"]:
            desired_billing_account["Chargify_Payment_Profile_ID__c"] = str(clean_profile_id)
        schedules_by_account: dict[str, list[dict[str, Any]]] = {}
        for row in structure["billingSchedules"]:
            schedules_by_account.setdefault(
                str(row.get("NovaPOS_Billing_Account__c") or ""),
                [],
            ).append(row)
        detached_billing_accounts: list[dict[str, Any]] = []
        preserved_billing_accounts: list[dict[str, Any]] = []
        canonical_account_id = str((billing_account or {}).get("Id") or "")
        if schedule_parent is not None:
            for row in customer_matches:
                row_id = str(row.get("Id") or "")
                if not row_id or row_id == canonical_account_id:
                    continue
                owned_schedules = schedules_by_account.get(row_id, [])
                if owned_schedules:
                    owned_subscription_ids = sorted(
                        {
                            value
                            for owned_schedule in owned_schedules
                            for value in (
                                _numeric_identifier(
                                    owned_schedule.get("Chargify_Subscription_ID__c")
                                ),
                                _numeric_identifier(
                                    owned_schedule.get("Billing_Circle_Schedule_ID__c")
                                ),
                            )
                            if value is not None
                        }
                    )
                    if (
                        not owned_subscription_ids
                        or clean_subscription_id in owned_subscription_ids
                    ):
                        raise SalesforceScopeError(
                            "another Billing Account ambiguously owns the requested subscription"
                        )
                    preserved_billing_accounts.append(
                        {
                            "billingAccountId": row_id,
                            "billingCircleClientId": row.get(
                                "Billing_Circle_Client_ID__c"
                            ),
                            "scheduleIds": sorted(
                                str(owned_schedule.get("Id") or "")
                                for owned_schedule in owned_schedules
                            ),
                            "subscriptionIds": owned_subscription_ids,
                        }
                    )
                    continue
                detached_billing_accounts.append(
                    {
                        "billingAccountId": row_id,
                        "before": {
                            "Billing_Circle_Client_ID__c": row.get(
                                "Billing_Circle_Client_ID__c"
                            ),
                            "Status__c": row.get("Status__c"),
                        },
                        "desired": {
                            "Billing_Circle_Client_ID__c": None,
                            "Status__c": "Inactive",
                        },
                    }
                )
        preserve_target_customer_id = bool(
            schedule_parent is not None and preserved_billing_accounts
        )
        if preserve_target_customer_id and not (
            clean_billing_account_id and clean_billing_schedule_id
        ):
            raise SalesforceScopeError(
                "shared-customer schedule ownership requires exact billing_account_id "
                "and billing_schedule_id selectors"
            )
        if preserve_target_customer_id:
            desired_billing_account["Billing_Circle_Client_ID__c"] = (
                billing_account or {}
            ).get("Billing_Circle_Client_ID__c")
        else:
            desired_billing_account["Billing_Circle_Client_ID__c"] = clean_customer_id
        desired_schedule = {
            "NovaPOS_Billing_Account__c": (
                str(billing_account.get("Id") or "")
                if billing_account
                else "__NEW_BILLING_ACCOUNT__"
            ),
            "Name": str(clean_subscription_id)[:80],
            "Title__c": str(clean_subscription_id),
            "Schedule_Interval__c": "monthly",
            "Bill_Amount__c": float(
                (Decimal(clean_bill_cents) / Decimal(100)).quantize(Decimal("0.01"))
            ),
            "Start_Date__c": clean_start_date,
            "Billing_Circle_Schedule_ID__c": clean_subscription_id,
            "Chargify_Subscription_ID__c": clean_subscription_id,
            "Type__c": "subscription",
        }
        locations = self.read_account_locations(clean_account_id, limit=500)["records"]
        locations_by_nova_id: dict[int, dict[str, Any]] = {}
        if clean_salesforce_location_ids:
            if len(clean_salesforce_location_ids) != len(clean_location_ids):
                raise SalesforceScopeError(
                    "salesforce_location_ids must select exactly one Salesforce record "
                    "for every requested Nova location"
                )
            locations_by_record_id = {
                str(location.get("Id") or ""): location for location in locations
            }
            selected_locations = [
                locations_by_record_id.get(record_id)
                for record_id in clean_salesforce_location_ids
            ]
            if any(location is None for location in selected_locations):
                raise SalesforceScopeError(
                    "salesforce_location_ids did not all resolve under the exact Account"
                )
            for location in selected_locations:
                assert location is not None
                numeric_id = _numeric_identifier(location.get("Location_ID__c"))
                if numeric_id not in clean_location_ids:
                    raise SalesforceScopeError(
                        "salesforce_location_ids selected a record outside nova_location_ids"
                    )
                locations_by_nova_id[numeric_id] = location
            if set(locations_by_nova_id) != set(clean_location_ids):
                raise SalesforceScopeError(
                    "salesforce_location_ids must select one distinct record for every "
                    "requested Nova location"
                )
        else:
            for location in locations:
                numeric_id = _numeric_identifier(location.get("Location_ID__c"))
                if numeric_id and numeric_id in clean_location_ids:
                    if numeric_id in locations_by_nova_id:
                        raise SalesforceScopeError(
                            f"Nova location {numeric_id} resolves to multiple Salesforce locations; "
                            "pass exact salesforce_location_ids after verifying the canonical records"
                        )
                    locations_by_nova_id[numeric_id] = location
        missing = sorted(set(clean_location_ids) - set(locations_by_nova_id))
        if missing:
            raise SalesforceScopeError(
                f"nova_location_ids did not resolve under the exact Account: {missing}"
            )
        account_needs_create = billing_account is None
        account_changes = (
            desired_billing_account
            if account_needs_create
            else {
                field: value
                for field, value in desired_billing_account.items()
                if field != "Account__c"
                and not _salesforce_field_matches(billing_account.get(field), value, field)
            }
        )
        schedule_needs_create = schedule is None
        schedule_changes = (
            desired_schedule
            if schedule_needs_create
            else {
                field: value
                for field, value in desired_schedule.items()
                if field != "NovaPOS_Billing_Account__c"
                and not _salesforce_field_matches(schedule.get(field), value, field)
            }
        )
        location_changes: list[dict[str, Any]] = []
        for nova_location_id_value in clean_location_ids:
            row = locations_by_nova_id[nova_location_id_value]
            desired_location = {
                "Chargify_Subscription_ID__c": str(clean_subscription_id),
                "NovaPOS_Billing_Schedule__c": (
                    str(schedule.get("Id") or "") if schedule else "__NEW_BILLING_SCHEDULE__"
                ),
            }
            if any(
                not _salesforce_field_matches(row.get(field), value, field)
                for field, value in desired_location.items()
                if not str(value).startswith("__NEW_")
            ) or schedule_needs_create:
                location_changes.append(
                    {
                        "locationId": str(row.get("Id") or ""),
                        "novaLocationId": nova_location_id_value,
                        "before": {
                            "Chargify_Subscription_ID__c": row.get(
                                "Chargify_Subscription_ID__c"
                            ),
                            "NovaPOS_Billing_Schedule__c": row.get(
                                "NovaPOS_Billing_Schedule__c"
                            ),
                        },
                        "desired": desired_location,
                    }
                )
        active_schedule_change = bool(
            structure["optionalBillingFieldsAvailable"]
            and (
                account_needs_create
                or schedule_needs_create
                or not _salesforce_field_matches(
                    (billing_account or {}).get("Active_Schedule__c"),
                    (schedule or {}).get("Id"),
                    "Active_Schedule__c",
                )
            )
        )
        duplicate = not any(
            [
                account_needs_create,
                bool(account_changes),
                schedule_needs_create,
                bool(schedule_changes),
                bool(detached_billing_accounts),
                bool(location_changes),
                active_schedule_change,
            ]
        )
        plan = {
            "operation": "salesforce_billing_structure_alignment",
            "ticketId": str(ticket.get("Id") or ticket_id),
            "ticketNumber": str(ticket.get("Name") or ""),
            "accountId": clean_account_id,
            "maxioCustomerId": clean_customer_id,
            "paymentProfileId": clean_profile_id,
            "subscriptionId": clean_subscription_id,
            "subscriptionState": clean_state,
            "billAmountCents": clean_bill_cents,
            "startDate": clean_start_date,
            "novaLocationIds": clean_location_ids,
            "salesforceLocationIds": sorted(
                str(row.get("Id") or "") for row in locations_by_nova_id.values()
            ),
            "billingAccountSelector": clean_billing_account_id,
            "billingScheduleSelector": clean_billing_schedule_id,
            "customerIdOwnershipMode": (
                "preserve_schedule_owners"
                if preserve_target_customer_id
                else "canonical_customer"
            ),
            "optionalBillingFieldsAvailable": structure["optionalBillingFieldsAvailable"],
            "billingAccount": {
                "existingId": str((billing_account or {}).get("Id") or ""),
                "create": account_needs_create,
                "changes": account_changes,
                "desired": desired_billing_account,
            },
            "billingSchedule": {
                "existingId": str((schedule or {}).get("Id") or ""),
                "create": schedule_needs_create,
                "changes": schedule_changes,
                "desired": desired_schedule,
            },
            "detachedBillingAccounts": detached_billing_accounts,
            "preservedBillingAccounts": preserved_billing_accounts,
            "locationChanges": location_changes,
            "activeScheduleChange": active_schedule_change,
            "duplicate": duplicate,
        }
        return {
            "ok": True,
            "status": "preview",
            "verified": True,
            **plan,
            "planHash": _stable_plan_hash(plan),
            "writesPerformed": False,
            "financialEffectsAuthorized": False,
        }

    def apply_billing_structure_alignment(
        self,
        ticket_id: str,
        account_id: str,
        *,
        maxio_customer_id: int,
        payment_profile_id: int | None,
        subscription_id: int,
        subscription_state: str,
        bill_amount_cents: int,
        start_date: str,
        nova_location_ids: list[int],
        preview_hash: str,
        idempotency_key: str,
        salesforce_location_ids: list[str] | None = None,
        billing_account_id: str = "",
        billing_schedule_id: str = "",
    ) -> dict[str, Any]:
        """Create/sync one Billing Account and Schedule, link locations, and verify all rows."""

        clean_key = _required_idempotency_key(idempotency_key)
        clean_hash = _required_preview_hash(preview_hash)
        preview = self.billing_structure_alignment_preview(
            ticket_id,
            account_id,
            maxio_customer_id=maxio_customer_id,
            payment_profile_id=payment_profile_id,
            subscription_id=subscription_id,
            subscription_state=subscription_state,
            bill_amount_cents=bill_amount_cents,
            start_date=start_date,
            nova_location_ids=nova_location_ids,
            salesforce_location_ids=salesforce_location_ids,
            billing_account_id=billing_account_id,
            billing_schedule_id=billing_schedule_id,
        )
        if preview["planHash"] != clean_hash:
            raise SalesforceScopeError(
                "preview_hash does not match the current Salesforce billing-structure plan"
            )
        if preview["duplicate"]:
            return {
                **preview,
                "status": "completed",
                "updated": False,
                "duplicate": True,
                "idempotencyKey": clean_key,
                "readback": self.read_billing_structure(account_id),
            }
        target = f"{preview['accountId']}:{preview['subscriptionId']}"
        with self._salesforce_operation(
            clean_key,
            "billing_structure_alignment",
            target,
            clean_hash,
        ) as prior:
            if prior is not None:
                return {**prior, "duplicate": True, "idempotencyKey": clean_key}

            billing_account_id = preview["billingAccount"]["existingId"]
            account_created = False
            # Empty partial Billing Accounts may already own the desired unique
            # Maxio customer ID. Detach those verified rows before assigning the
            # ID to the canonical schedule parent or creating its replacement.
            for row in preview["detachedBillingAccounts"]:
                self._request(
                    "PATCH",
                    f"/sobjects/NovaPOS_Billing_Account__c/{row['billingAccountId']}",
                    json=dict(row["desired"]),
                )

            if preview["billingAccount"]["create"]:
                created = self._request(
                    "POST",
                    "/sobjects/NovaPOS_Billing_Account__c",
                    json=dict(preview["billingAccount"]["desired"]),
                )
                billing_account_id = _required_id(
                    str(created.get("id") or ""),
                    "created billing account id",
                )
                account_created = True
            elif preview["billingAccount"]["changes"]:
                self._request(
                    "PATCH",
                    f"/sobjects/NovaPOS_Billing_Account__c/{billing_account_id}",
                    json=dict(preview["billingAccount"]["changes"]),
                )

            schedule_id = preview["billingSchedule"]["existingId"]
            schedule_created = False
            schedule_payload = dict(preview["billingSchedule"]["desired"])
            schedule_payload["NovaPOS_Billing_Account__c"] = billing_account_id
            if preview["billingSchedule"]["create"]:
                created = self._request(
                    "POST",
                    "/sobjects/NovaPOS_Billing_Schedule__c",
                    json=schedule_payload,
                )
                schedule_id = _required_id(
                    str(created.get("id") or ""),
                    "created billing schedule id",
                )
                schedule_created = True
            else:
                schedule_changes = dict(preview["billingSchedule"]["changes"])
                existing_billing_account_id = str(
                    self._read_billing_schedule(schedule_id).get(
                        "NovaPOS_Billing_Account__c"
                    )
                    or ""
                )
                if existing_billing_account_id != billing_account_id:
                    schedule_changes["NovaPOS_Billing_Account__c"] = billing_account_id
                if schedule_changes:
                    self._request(
                        "PATCH",
                        f"/sobjects/NovaPOS_Billing_Schedule__c/{schedule_id}",
                        json=schedule_changes,
                    )

            billing_account_link_payload: dict[str, Any] = {"Status__c": "Active"}
            if preview["optionalBillingFieldsAvailable"]:
                billing_account_link_payload["Active_Schedule__c"] = schedule_id
            self._request(
                "PATCH",
                f"/sobjects/NovaPOS_Billing_Account__c/{billing_account_id}",
                json=billing_account_link_payload,
            )
            for row in preview["locationChanges"]:
                self._request(
                    "PATCH",
                    f"/sobjects/NovaPOS_Location__c/{row['locationId']}",
                    json={
                        "Chargify_Subscription_ID__c": str(preview["subscriptionId"]),
                        "NovaPOS_Billing_Schedule__c": schedule_id,
                    },
                )

            structure = self.read_billing_structure(preview["accountId"])
            account_readback = next(
                (
                    row
                    for row in structure["billingAccounts"]
                    if str(row.get("Id") or "") == billing_account_id
                ),
                None,
            )
            schedule_readback = next(
                (
                    row
                    for row in structure["billingSchedules"]
                    if str(row.get("Id") or "") == schedule_id
                ),
                None,
            )
            if not account_readback or not schedule_readback:
                raise SalesforceUnavailableError(
                    "Salesforce billing-structure readback was incomplete; do not retry"
                )
            if any(
                field != "Account__c"
                and not _salesforce_field_matches(
                    account_readback.get(field),
                    value,
                    field,
                )
                for field, value in preview["billingAccount"]["desired"].items()
            ):
                raise SalesforceUnavailableError(
                    "Salesforce Billing Account readback did not match the desired structure; "
                    "do not retry"
                )
            if any(
                not _salesforce_field_matches(
                    schedule_readback.get(field),
                    value,
                    field,
                )
                for field, value in preview["billingSchedule"]["desired"].items()
            ):
                raise SalesforceUnavailableError(
                    "Salesforce Billing Schedule readback did not match the desired structure; "
                    "do not retry"
                )
            if (
                preview["optionalBillingFieldsAvailable"]
                and str(account_readback.get("Active_Schedule__c") or "") != schedule_id
            ):
                raise SalesforceUnavailableError(
                    "Salesforce Billing Account active-schedule readback did not match; do not retry"
                )
            if _numeric_identifier(
                schedule_readback.get("Chargify_Subscription_ID__c")
            ) != preview["subscriptionId"]:
                raise SalesforceUnavailableError(
                    "Salesforce Billing Schedule subscription readback did not match; do not retry"
                )
            detached_ids = {
                row["billingAccountId"] for row in preview["detachedBillingAccounts"]
            }
            detached_readback = [
                row
                for row in structure["billingAccounts"]
                if str(row.get("Id") or "") in detached_ids
            ]
            if len(detached_readback) != len(detached_ids) or any(
                _numeric_identifier(row.get("Billing_Circle_Client_ID__c")) is not None
                or str(row.get("Status__c") or "").strip().casefold() != "inactive"
                for row in detached_readback
            ):
                raise SalesforceUnavailableError(
                    "Salesforce detached Billing Account readback did not match; do not retry"
                )
            preserved_ids = {
                row["billingAccountId"] for row in preview["preservedBillingAccounts"]
            }
            preserved_readback = {
                str(row.get("Id") or ""): row
                for row in structure["billingAccounts"]
                if str(row.get("Id") or "") in preserved_ids
            }
            schedules_by_parent: dict[str, list[dict[str, Any]]] = {}
            for row in structure["billingSchedules"]:
                schedules_by_parent.setdefault(
                    str(row.get("NovaPOS_Billing_Account__c") or ""),
                    [],
                ).append(row)
            for preserved in preview["preservedBillingAccounts"]:
                preserved_id = preserved["billingAccountId"]
                record = preserved_readback.get(preserved_id)
                current_schedule_ids = sorted(
                    str(row.get("Id") or "")
                    for row in schedules_by_parent.get(preserved_id, [])
                )
                if (
                    record is None
                    or not _salesforce_field_matches(
                        record.get("Billing_Circle_Client_ID__c"),
                        preserved["billingCircleClientId"],
                        "Billing_Circle_Client_ID__c",
                    )
                    or current_schedule_ids != preserved["scheduleIds"]
                ):
                    raise SalesforceUnavailableError(
                        "Salesforce preserved Billing Account ownership readback did not match; "
                        "do not retry"
                    )
            locations = self.read_account_locations(preview["accountId"], limit=500)["records"]
            expected_locations = set(preview["novaLocationIds"])
            expected_salesforce_locations = set(preview["salesforceLocationIds"])
            verified_locations = {
                _numeric_identifier(row.get("Location_ID__c"))
                for row in locations
                if str(row.get("Id") or "") in expected_salesforce_locations
                and _numeric_identifier(row.get("Chargify_Subscription_ID__c"))
                == preview["subscriptionId"]
                and str(row.get("NovaPOS_Billing_Schedule__c") or "") == schedule_id
            }
            verified_salesforce_locations = {
                str(row.get("Id") or "")
                for row in locations
                if str(row.get("Id") or "") in expected_salesforce_locations
                and _numeric_identifier(row.get("Chargify_Subscription_ID__c"))
                == preview["subscriptionId"]
                and str(row.get("NovaPOS_Billing_Schedule__c") or "") == schedule_id
            }
            if (
                verified_locations != expected_locations
                or verified_salesforce_locations != expected_salesforce_locations
            ):
                raise SalesforceUnavailableError(
                    "Salesforce location billing-link readback did not match; do not retry"
                )
            result = {
                **preview,
                "status": "completed",
                "updated": True,
                "duplicate": False,
                "verified": True,
                "idempotencyKey": clean_key,
                "billingAccountId": billing_account_id,
                "billingAccountCreated": account_created,
                "billingScheduleId": schedule_id,
                "billingScheduleCreated": schedule_created,
                "detachedBillingAccountsVerified": sorted(detached_ids),
                "preservedBillingAccountsVerified": sorted(preserved_ids),
                "locationsVerified": sorted(verified_locations),
                "salesforceLocationsVerified": sorted(verified_salesforce_locations),
                "readback": {
                    "billingAccount": account_readback,
                    "billingSchedule": schedule_readback,
                },
                "financialEffectsAuthorized": False,
            }
            self._complete_salesforce_operation(
                clean_key,
                "billing_structure_alignment",
                target,
                clean_hash,
                result,
            )
            return result

    def _assert_billing_ticket_account(
        self,
        ticket_id: str,
        account_id: str,
    ) -> dict[str, Any]:
        clean_ticket_id = _required_id(ticket_id, "ticket_id")
        clean_account_id = _required_id(account_id, "account_id")
        self._assert_ticket_scope(clean_ticket_id, {"3. Billing"})
        ticket = self.read_ticket(clean_ticket_id)["record"]
        if str(ticket.get("Account__c") or "") != clean_account_id:
            raise SalesforceScopeError("ticket_id is not linked to the requested Salesforce Account")
        return ticket

    def _assert_operational_ticket_account(
        self,
        ticket_id: str,
        account_id: str,
    ) -> dict[str, Any]:
        """Require one exact customer-operation ticket without inventing lane ownership."""

        clean_ticket_id = _required_id(ticket_id, "ticket_id")
        clean_account_id = _required_id(account_id, "account_id")
        self._assert_ticket_scope(clean_ticket_id, OPERATIONAL_TICKET_RECORD_TYPES)
        ticket = self.read_ticket(clean_ticket_id)["record"]
        if str(ticket.get("Account__c") or "") != clean_account_id:
            raise SalesforceScopeError("ticket_id is not linked to the requested Salesforce Account")
        return ticket

    def _read_billing_schedule(self, schedule_id: str) -> dict[str, Any]:
        clean_id = _required_id(schedule_id, "billing_schedule_id")
        result = self._query(
            "SELECT Id,NovaPOS_Billing_Account__c,"
            "NovaPOS_Billing_Account__r.Account__c,Chargify_Subscription_ID__c,"
            "Billing_Circle_Schedule_ID__c,Start_Date__c "
            f"FROM NovaPOS_Billing_Schedule__c WHERE Id = '{clean_id}' LIMIT 1"
        )
        records = [record for record in result.get("records", []) if isinstance(record, dict)]
        if len(records) != 1:
            raise SalesforceScopeError(
                "billing_schedule_id did not resolve to exactly one Salesforce schedule"
            )
        record = dict(records[0])
        related = (
            record.pop("NovaPOS_Billing_Account__r", None)
            if isinstance(record.get("NovaPOS_Billing_Account__r"), dict)
            else {}
        )
        record["Account__c"] = str(related.get("Account__c") or "")
        return record

    def _assert_account_cancellation_ticket(
        self,
        ticket_id: str,
        account_id: str,
    ) -> dict[str, Any]:
        clean_ticket_id = _required_id(ticket_id, "ticket_id")
        clean_account_id = _required_id(account_id, "account_id")
        ticket = self.read_ticket(clean_ticket_id)["record"]
        if str(ticket.get("Account__c") or "") != clean_account_id:
            raise SalesforceScopeError("ticket_id is not linked to the requested Salesforce Account")
        text = "\n".join(
            str(ticket.get(key) or "")
            for key in (
                "Description__c",
                "Reason_for_closing_the_account__c",
                "Accounts_or_Order_Issue__c",
            )
        )
        if not ACCOUNT_CANCELLATION_RE.search(text) and not str(
            ticket.get("Reason_for_closing_the_account__c") or ""
        ).strip():
            raise SalesforceScopeError("ticket_id does not contain a verified account-cancellation request")
        return ticket

    def _resolve_cancellation_order_record_type(self) -> dict[str, Any]:
        aliases = {alias.casefold() for alias in CANCELLATION_ORDER_RECORD_TYPE_ALIASES}
        result = self._query(
            "SELECT Id,Name,DeveloperName FROM RecordType "
            "WHERE SobjectType = 'NovaPOS_Order__c' AND IsActive = true LIMIT 100"
        )
        matches = [
            dict(record)
            for record in result.get("records", [])
            if isinstance(record, dict)
            and (
                str(record.get("DeveloperName") or "").casefold() in aliases
                or str(record.get("Name") or "").casefold() in aliases
            )
        ]
        if len(matches) != 1:
            raise SalesforceScopeError(
                "Salesforce cancellation-order RecordType did not resolve to exactly one active record type"
            )
        matches[0].pop("attributes", None)
        return matches[0]

    def _resolve_order_picklist_value(
        self,
        record_type_id: str,
        field_name: str,
        requested_value: str,
        *,
        required: bool = True,
    ) -> str | None:
        clean_record_type = _required_id(record_type_id, "record_type_id")
        if field_name not in {"Reason_for_cancellation__c", "Existing_Order_Type__c"}:
            raise SalesforceScopeError("Order picklist field is not allowed")
        result = self._request(
            "GET",
            f"/ui-api/object-info/NovaPOS_Order__c/picklist-values/{clean_record_type}/{field_name}",
        )
        values = [
            entry
            for entry in (result.get("values") if isinstance(result, dict) else [])
            if isinstance(entry, dict) and entry.get("active", True)
        ]
        requested = _normalized_picklist_text(requested_value)
        matches = [
            str(entry.get("value") or "").strip()
            for entry in values
            if requested
            in {
                _normalized_picklist_text(entry.get("value")),
                _normalized_picklist_text(entry.get("label")),
            }
        ]
        matches = sorted({value for value in matches if value})
        if not matches and field_name == "Reason_for_cancellation__c":
            alias = CANCELLATION_REASON_ALIASES.get(requested)
            if alias:
                normalized_alias = _normalized_picklist_text(alias)
                matches = sorted(
                    {
                        str(entry.get("value") or "").strip()
                        for entry in values
                        if normalized_alias
                        in {
                            _normalized_picklist_text(entry.get("value")),
                            _normalized_picklist_text(entry.get("label")),
                        }
                        and str(entry.get("value") or "").strip()
                    }
                )
        if not matches and not required:
            return None
        if len(matches) != 1:
            allowed = ", ".join(str(entry.get("label") or entry.get("value") or "") for entry in values[:20])
            raise SalesforceScopeError(
                f"{field_name} value did not resolve exactly; allowed labels: {allowed or 'unavailable'}"
            )
        return matches[0]

    def _order_approval_state(self, order_id: str) -> dict[str, Any]:
        if not SALESFORCE_ID.fullmatch(str(order_id or "")):
            return {"submitted": False, "records": []}
        return self._order_approval_states([order_id]).get(
            order_id,
            {"submitted": False, "status": "", "records": []},
        )

    def _order_approval_states(self, order_ids: list[str]) -> dict[str, dict[str, Any]]:
        clean_ids = sorted({value for value in order_ids if SALESFORCE_ID.fullmatch(value)})[:100]
        if not clean_ids:
            return {}
        quoted = ",".join(f"'{value}'" for value in clean_ids)
        result = self._query(
            "SELECT Id,Status,TargetObjectId,SubmittedById,CreatedDate,LastActorId "
            f"FROM ProcessInstance WHERE TargetObjectId IN ({quoted}) "
            "ORDER BY CreatedDate DESC LIMIT 500"
        )
        grouped: dict[str, list[dict[str, Any]]] = {}
        for record in result.get("records", []):
            if not isinstance(record, dict):
                continue
            target_id = str(record.get("TargetObjectId") or "")
            if target_id in clean_ids:
                grouped.setdefault(target_id, []).append(_bounded_record(record))
        return {
            order_id: {
                "submitted": bool(grouped.get(order_id)),
                "status": str(grouped[order_id][0].get("Status") or "") if grouped.get(order_id) else "",
                "records": grouped.get(order_id, []),
            }
            for order_id in clean_ids
        }

    def _ticket_content_versions(self, ticket_id: str) -> list[dict[str, Any]]:
        clean_ticket_id = _required_id(ticket_id, "ticket_id")
        links = self._query(
            "SELECT ContentDocumentId FROM ContentDocumentLink "
            f"WHERE LinkedEntityId = '{clean_ticket_id}' LIMIT 100"
        )
        document_ids = sorted(
            {
                str(record.get("ContentDocumentId") or "")
                for record in links.get("records", [])
                if isinstance(record, dict)
                and SALESFORCE_ID.fullmatch(str(record.get("ContentDocumentId") or ""))
            }
        )
        if not document_ids:
            return []
        quoted = ",".join(f"'{value}'" for value in document_ids)
        result = self._query(
            "SELECT Id,ContentDocumentId,Title,PathOnClient,ContentSize,FileType,CreatedDate "
            "FROM ContentVersion WHERE IsLatest = true "
            f"AND ContentDocumentId IN ({quoted}) ORDER BY CreatedDate DESC LIMIT 100"
        )
        return [
            _bounded_record(record)
            for record in result.get("records", [])
            if isinstance(record, dict)
        ]

    def ticket_pdf_status(
        self,
        ticket_id: str,
        file_name: str,
        sha256: str,
        *,
        allowed_record_types: Collection[str] | None = None,
    ) -> dict[str, Any]:
        """Read exact PDF duplicate and digest evidence for one lane-owned ticket."""

        clean_name, clean_digest = _validated_cancellation_pdf_identity(file_name, sha256)
        return self.ticket_attachment_status(
            ticket_id,
            clean_name,
            clean_digest,
            allowed_record_types=allowed_record_types,
        )

    def ticket_attachment_status(
        self,
        ticket_id: str,
        file_name: str,
        sha256: str,
        *,
        allowed_record_types: Collection[str] | None = None,
    ) -> dict[str, Any]:
        """Read exact bounded attachment duplicate and digest evidence for one lane-owned ticket."""

        clean_ticket_id = _required_id(ticket_id, "ticket_id")
        self._assert_ticket_scope(clean_ticket_id, allowed_record_types)
        clean_name, clean_digest = _validated_ticket_attachment_identity(file_name, sha256)
        title = Path(clean_name).stem.casefold()
        matching_title: list[dict[str, Any]] = []
        exact_matches: list[dict[str, Any]] = []
        for record in self._ticket_content_versions(clean_ticket_id):
            if str(record.get("Title") or "").casefold() != title:
                continue
            candidate = dict(record)
            version_id = _required_id(str(candidate.get("Id") or ""), "existing ContentVersion id")
            candidate_digest = hashlib.sha256(
                self._request_bytes(f"/sobjects/ContentVersion/{version_id}/VersionData")
            ).hexdigest()
            candidate["sha256"] = candidate_digest
            matching_title.append(candidate)
            if candidate_digest == clean_digest:
                exact_matches.append(candidate)
        return {
            "ok": True,
            "verified": True,
            "duplicate": bool(exact_matches),
            "conflictingTitle": bool(matching_title and not exact_matches),
            "ticketId": clean_ticket_id,
            "fileName": clean_name,
            "sha256": clean_digest,
            "contentVersion": exact_matches[0] if exact_matches else None,
            "matchingTitleVersions": matching_title,
            "writesPerformed": False,
        }

    def upload_ticket_pdf(
        self,
        ticket_id: str,
        file_name: str,
        content_base64: str,
        sha256: str,
        *,
        idempotency_key: str,
        allowed_record_types: Collection[str] | None = None,
    ) -> dict[str, Any]:
        """Attach one verified PDF to a lane-owned ticket with digest readback."""

        clean_name, clean_digest = _validated_cancellation_pdf_identity(file_name, sha256)
        return self.upload_ticket_attachment(
            ticket_id,
            clean_name,
            content_base64,
            clean_digest,
            idempotency_key=idempotency_key,
            allowed_record_types=allowed_record_types,
        )

    def upload_ticket_attachment(
        self,
        ticket_id: str,
        file_name: str,
        content_base64: str,
        sha256: str,
        *,
        idempotency_key: str,
        allowed_record_types: Collection[str] | None = None,
    ) -> dict[str, Any]:
        """Attach one verified bounded file to a lane-owned ticket with digest readback."""

        clean_ticket_id = _required_id(ticket_id, "ticket_id")
        self._assert_ticket_scope(clean_ticket_id, allowed_record_types)
        clean_key = _required_idempotency_key(idempotency_key)
        clean_name, clean_digest = _validated_ticket_attachment_identity(file_name, sha256)
        try:
            content = base64.b64decode(str(content_base64 or ""), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise SalesforceScopeError("content_base64 must be valid base64") from exc
        if not content or len(content) > MAX_TICKET_ATTACHMENT_BYTES:
            raise SalesforceScopeError("ticket attachment must be between 1 byte and 10 MiB")
        _validate_ticket_attachment_content(clean_name, content)
        if hashlib.sha256(content).hexdigest() != clean_digest:
            raise SalesforceScopeError("sha256 does not match the ticket attachment")

        status = self.ticket_attachment_status(
            clean_ticket_id,
            clean_name,
            clean_digest,
            allowed_record_types=allowed_record_types,
        )
        if status["duplicate"]:
            return {
                **status,
                "uploaded": False,
                "idempotencyKey": clean_key,
            }
        if status["conflictingTitle"]:
            raise SalesforceScopeError("a different file with the same title is already attached")
        created = self._request(
            "POST",
            "/sobjects/ContentVersion",
            json={
                "Title": Path(clean_name).stem,
                "PathOnClient": clean_name,
                "VersionData": base64.b64encode(content).decode("ascii"),
                "FirstPublishLocationId": clean_ticket_id,
            },
        )
        version_id = _required_id(str(created.get("id") or ""), "created ContentVersion id")
        readback_status = self.ticket_attachment_status(
            clean_ticket_id,
            clean_name,
            clean_digest,
            allowed_record_types=allowed_record_types,
        )
        readback = readback_status.get("contentVersion")
        if (
            not readback_status.get("duplicate")
            or not isinstance(readback, dict)
            or str(readback.get("Id") or "") != version_id
        ):
            raise SalesforceUnavailableError(
                "Salesforce accepted the attachment upload but digest readback was not verified; do not retry"
            )
        return {
            **readback_status,
            "uploaded": True,
            "duplicate": False,
            "idempotencyKey": clean_key,
        }

    def approved_email_template_inventory(self, *, lane: str = "direct_codex") -> dict[str, Any]:
        """Return classified approved-folder templates and exact server-owned route policy."""

        folder_ids = ",".join(f"'{folder_id}'" for folder_id in APPROVED_EMAIL_TEMPLATE_FOLDERS)
        result = self._query(
            "SELECT Id,Name,DeveloperName,FolderId,TemplateType,IsActive,Subject,"
            "BrandTemplateId,Description,LastModifiedDate FROM EmailTemplate "
            f"WHERE IsActive = true AND FolderId IN ({folder_ids}) ORDER BY FolderId,Name"
        )
        clean_lane = _required_email_lane(lane)
        raw_records = [
            dict(record)
            for record in result.get("records", [])
            if isinstance(record, dict)
        ]
        identity_counts: dict[tuple[str, str], int] = {}
        for raw in raw_records:
            identity = (
                str(raw.get("FolderId") or "")[:15],
                str(raw.get("DeveloperName") or ""),
            )
            identity_counts[identity] = identity_counts.get(identity, 0) + 1
        pending_by_name = {
            candidate_name: workflow
            for workflow in CANONICAL_PENDING_EMAIL_WORKFLOWS
            for candidate_name in workflow["acceptedNames"]
        }

        templates: list[dict[str, Any]] = []
        seen_identities: set[tuple[str, str]] = set()
        seen_pending_situations: set[str] = set()
        for raw in raw_records:
            folder_id = str(raw.get("FolderId") or "")
            folder_key = folder_id[:15]
            name = str(raw.get("Name") or "")
            developer_name = str(raw.get("DeveloperName") or "")
            identity = (folder_key, developer_name)
            seen_identities.add(identity)
            spec = EMAIL_TEMPLATE_REGISTRY.get(identity)
            pending_spec = pending_by_name.get(name)
            policy = spec or pending_spec
            classification = EMAIL_TEMPLATE_CLASS_PENDING
            classification_reason = "active template has not completed curated review"
            metadata_matches = False
            if pending_spec:
                seen_pending_situations.add(str(pending_spec["situation"]))
                classification = str(pending_spec["classification"])
                classification_reason = str(pending_spec["rejectionReason"])
            if spec:
                classification = str(spec["classification"])
                classification_reason = "curated registry policy matched"
                metadata_matches = (
                    identity_counts.get(identity) == 1
                    and name == str(spec["name"])
                    and str(raw.get("Subject") or "") == str(spec["subject"])
                    and (
                        not spec.get("expectedTemplateId")
                        or str(raw.get("Id") or "") == str(spec["expectedTemplateId"])
                    )
                )
                if identity_counts.get(identity) != 1:
                    classification = EMAIL_TEMPLATE_CLASS_BROKEN
                    classification_reason = "template identity is not unique in its approved folder"
                elif not metadata_matches:
                    classification = EMAIL_TEMPLATE_CLASS_BROKEN
                    classification_reason = "template name, subject, or fixed record identity drifted"
            curated_rejection_reason = _curated_email_template_rejection_reason(raw)
            if curated_rejection_reason:
                classification = EMAIL_TEMPLATE_CLASS_REJECTED
                classification_reason = curated_rejection_reason
            owning_lanes = (
                tuple(str(value) for value in policy.get("owningLanes", ()))
                if policy
                else ()
            )
            registry_sendable = (
                bool(spec)
                and classification == EMAIL_TEMPLATE_CLASS_APPROVED
                and metadata_matches
                and bool(spec.get("sendTool"))
            )
            templates.append(
                {
                    "id": str(raw.get("Id") or ""),
                    "name": name,
                    "developerName": developer_name,
                    "folderId": folder_id,
                    "folder": APPROVED_EMAIL_TEMPLATE_FOLDERS.get(folder_key, ""),
                    "templateType": str(raw.get("TemplateType") or ""),
                    "active": raw.get("IsActive") is True,
                    "subject": str(raw.get("Subject") or ""),
                    "brandTemplateId": str(raw.get("BrandTemplateId") or ""),
                    "description": str(raw.get("Description") or ""),
                    "lastModifiedDate": str(raw.get("LastModifiedDate") or ""),
                    "classification": classification,
                    "classificationReason": classification_reason,
                    "situation": (
                        str(policy.get("situation") or "") or None if policy else None
                    ),
                    "department": (
                        str(policy.get("department") or "") or None if policy else None
                    ),
                    "recipientPolicy": (
                        str(policy.get("recipientPolicy") or "") or None if policy else None
                    ),
                    "senderPolicy": (
                        str(policy.get("senderPolicy") or "") or None if policy else None
                    ),
                    "sensitivity": (
                        str(policy.get("sensitivity") or "") or None if policy else None
                    ),
                    "previewTool": (
                        str(policy.get("previewTool") or "") or None if policy else None
                    ),
                    "sendTool": (
                        str(policy.get("sendTool") or "") or None if policy else None
                    ),
                    "owningLanes": list(owning_lanes),
                    "registrySendable": registry_sendable,
                    "availableToLane": registry_sendable and clean_lane in owning_lanes,
                    "sendEnabled": registry_sendable and clean_lane in owning_lanes,
                    "requiredDetails": (
                        list(policy.get("detailFields") or ()) if policy else []
                    ),
                }
            )
        for identity, spec in EMAIL_TEMPLATE_REGISTRY.items():
            if identity in seen_identities:
                continue
            owning_lanes = tuple(str(value) for value in spec.get("owningLanes", ()))
            templates.append(
                {
                    "id": "",
                    "name": str(spec["name"]),
                    "developerName": str(spec["developerName"]),
                    "folderId": str(spec["folderId"]),
                    "folder": APPROVED_EMAIL_TEMPLATE_FOLDERS.get(str(spec["folderId"]), ""),
                    "templateType": "",
                    "active": False,
                    "subject": str(spec["subject"]),
                    "brandTemplateId": "",
                    "description": "",
                    "lastModifiedDate": "",
                    "classification": EMAIL_TEMPLATE_CLASS_MISSING,
                    "classificationReason": "curated template was not present and active",
                    "situation": str(spec["situation"]),
                    "department": str(spec["department"]),
                    "recipientPolicy": str(spec["recipientPolicy"]),
                    "senderPolicy": str(spec["senderPolicy"]),
                    "sensitivity": str(spec["sensitivity"]),
                    "previewTool": str(spec.get("previewTool") or "") or None,
                    "sendTool": str(spec.get("sendTool") or "") or None,
                    "owningLanes": list(owning_lanes),
                    "registrySendable": False,
                    "availableToLane": False,
                    "sendEnabled": False,
                    "requiredDetails": list(spec.get("detailFields") or ()),
                }
            )
        for workflow in CANONICAL_PENDING_EMAIL_WORKFLOWS:
            situation = str(workflow["situation"])
            if situation in seen_pending_situations:
                continue
            classification = str(workflow["classification"])
            classification_reason = str(workflow["rejectionReason"])
            if classification == EMAIL_TEMPLATE_CLASS_PENDING:
                classification = EMAIL_TEMPLATE_CLASS_MISSING
                classification_reason = (
                    "operator-approved workflow has no exact active reviewed template "
                    "in an approved folder"
                )
            owning_lanes = tuple(
                str(value) for value in workflow.get("owningLanes", ())
            )
            templates.append(
                {
                    "id": "",
                    "name": str(workflow["name"]),
                    "developerName": None,
                    "folderId": str(workflow["folderId"]),
                    "folder": APPROVED_EMAIL_TEMPLATE_FOLDERS.get(
                        str(workflow["folderId"]),
                        "",
                    ),
                    "templateType": "",
                    "active": False,
                    "subject": "",
                    "brandTemplateId": "",
                    "description": "",
                    "lastModifiedDate": "",
                    "classification": classification,
                    "classificationReason": classification_reason,
                    "situation": situation,
                    "department": str(workflow["department"]),
                    "recipientPolicy": str(workflow["recipientPolicy"]),
                    "senderPolicy": str(workflow["senderPolicy"]),
                    "sensitivity": str(workflow["sensitivity"]),
                    "previewTool": None,
                    "sendTool": None,
                    "owningLanes": list(owning_lanes),
                    "registrySendable": False,
                    "availableToLane": False,
                    "sendEnabled": False,
                    "requiredDetails": list(workflow.get("detailFields") or ()),
                }
            )
        return {
            "ok": True,
            "verified": True,
            "lane": clean_lane,
            "folders": [
                {"id": folder_id, "name": folder_name}
                for folder_id, folder_name in APPROVED_EMAIL_TEMPLATE_FOLDERS.items()
            ],
            "templates": templates,
            "count": len(templates),
            "situationCount": sum(1 for template in templates if template["sendEnabled"]),
            "freehandSubjectAllowed": False,
            "freehandBodyAllowed": False,
            "callerSelectedSenderAllowed": False,
            "writesPerformed": False,
        }

    def preview_ticket_template_email(
        self,
        *,
        ticket_id: str,
        situation: str,
        details: dict[str, Any] | None = None,
        lane: str = "direct_codex",
        allowed_record_types: Collection[str] | None = None,
    ) -> dict[str, Any]:
        """Render one fixed approved template and verify its wrapper/content without sending."""

        prepared = self._prepare_ticket_template_email(
            ticket_id=ticket_id,
            situation=situation,
            details=details,
            lane=lane,
            allowed_record_types=allowed_record_types,
        )
        return _public_ticket_template_preview(prepared)

    def send_ticket_template_email(
        self,
        *,
        ticket_id: str,
        situation: str,
        details: dict[str, Any] | None = None,
        lane: str = "direct_codex",
        allowed_record_types: Collection[str] | None = None,
        attachment_content_version_ids: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Send one fixed approved situation template after server-side preview validation."""

        prepared = self._prepare_ticket_template_email(
            ticket_id=ticket_id,
            situation=situation,
            details=details,
            lane=lane,
            allowed_record_types=allowed_record_types,
        )
        attachment_ids = self._verified_ticket_attachment_ids(
            ticket_id, attachment_content_version_ids
        )
        prepared["attachmentContentVersionIds"] = list(attachment_ids)
        idempotency_key, target, plan_hash = _ticket_template_delivery_identity(
            prepared,
            key_prefix="ticket-template-email",
        )
        operation = "salesforce_ticket_template_email_send"
        with self._salesforce_operation(
            idempotency_key,
            operation,
            target,
            plan_hash,
            track_provider_attempt=True,
            reconcile_pending=lambda: self._reconcile_approved_ticket_template_delivery(
                prepared
            ),
        ) as prior:
            if prior is not None:
                delivery = {
                    **prior,
                    "sent": False,
                    "duplicate": True,
                    "replayed": True,
                    "writesPerformed": False,
                    "providerResult": None,
                    "idempotencyKey": idempotency_key,
                }
            else:
                delivery = {
                    **self._deliver_approved_ticket_template(
                        prepared,
                        mark_provider_attempt=lambda: self._mark_salesforce_provider_attempt(
                            idempotency_key,
                            operation,
                            target,
                            plan_hash,
                        ),
                    ),
                    "replayed": False,
                    "idempotencyKey": idempotency_key,
                }
                delivery["writesPerformed"] = bool(delivery.get("sent"))
                self._complete_salesforce_operation(
                    idempotency_key,
                    operation,
                    target,
                    plan_hash,
                    delivery,
                )
        return {
            **delivery,
            "situation": prepared["situation"],
            "templateId": prepared["templateId"],
            "templateName": prepared["templateName"],
            "templateDeveloperName": prepared["templateDeveloperName"],
            "templatePreview": _public_ticket_template_preview(prepared),
            "callerSelectedRecipients": False,
            "callerSelectedSubject": False,
            "callerSelectedTemplate": False,
            "freehandBodyAccepted": False,
        }

    def preview_ticket_company_credentials_email(
        self,
        *,
        ticket_id: str,
        requested_recipients: list[str],
        lane: str,
        allowed_record_types: Collection[str] | None = None,
    ) -> dict[str, Any]:
        """Validate the one fixed ticket 347370 credential delivery without exposing secrets."""

        prepared = self._prepare_ticket_company_credentials_email(
            ticket_id=ticket_id,
            requested_recipients=requested_recipients,
            lane=lane,
            allowed_record_types=allowed_record_types,
        )
        return _public_sensitive_template_preview(prepared)

    def send_ticket_company_credentials_email(
        self,
        *,
        ticket_id: str,
        requested_recipients: list[str],
        lane: str,
        allowed_record_types: Collection[str] | None = None,
    ) -> dict[str, Any]:
        """Send the fixed ticket 347370 credential template with redacted receipts."""

        prepared = self._prepare_ticket_company_credentials_email(
            ticket_id=ticket_id,
            requested_recipients=requested_recipients,
            lane=lane,
            allowed_record_types=allowed_record_types,
        )
        return self._deliver_ticket_company_credentials_email(prepared)

    def _prepare_ticket_company_credentials_email(
        self,
        *,
        ticket_id: str,
        requested_recipients: list[str],
        lane: str,
        allowed_record_types: Collection[str] | None,
    ) -> dict[str, Any]:
        clean_ticket_id = _required_id(ticket_id, "ticket_id")
        if clean_ticket_id != CREDENTIALS_TICKET_ID:
            raise SalesforceScopeError(
                "company credentials email is restricted to exact ticket 347370"
            )
        clean_lane = _required_email_lane(lane)
        spec = APPROVED_TICKET_EMAIL_SITUATIONS["company_credentials_347370"]
        self._assert_email_template_lane(spec, clean_lane)
        self._assert_ticket_scope(clean_ticket_id, allowed_record_types)
        recipients = _validated_credentials_recipients(requested_recipients)
        ticket = dict(self.read_ticket(clean_ticket_id)["record"])
        if str(ticket.get("Name") or "").strip() != CREDENTIALS_TICKET_NUMBER:
            raise SalesforceUnavailableError(
                "exact ticket record no longer reads back as ticket 347370"
            )
        evidence_addresses = _positive_credentials_recipient_evidence(ticket)
        if any(
            recipient.casefold() not in evidence_addresses
            for recipient in recipients
        ):
            raise SalesforceScopeError(
                "requested credential recipients lack positive evidence on exact ticket 347370"
            )
        render_contact_id = _required_id(
            str(ticket.get("Contact__c") or ""),
            "ticket 347370 render Contact",
        )
        template = self._resolve_approved_email_template(
            "company_credentials_347370",
            lane=clean_lane,
            allow_specialized=True,
        )
        sender = self._resolve_department_sender("support")
        preview = self._render_stored_email_template(
            template_id=template["templateId"],
            recipient_id=render_contact_id,
            related_record_id=clean_ticket_id,
        )
        preview = _normalize_agent_email_signature(preview, department="support")
        validation = _verify_sensitive_template_preview(
            preview,
            expected_subject=template["subject"],
        )
        return {
            "ticketId": clean_ticket_id,
            "ticketNumber": CREDENTIALS_TICKET_NUMBER,
            "situation": "company_credentials_347370",
            "templateId": template["templateId"],
            "templateName": template["templateName"],
            "templateDeveloperName": template["templateDeveloperName"],
            "subject": template["subject"],
            "renderedPreview": preview,
            "validation": validation,
            "recipients": recipients,
            "sender": sender,
        }

    def _deliver_ticket_company_credentials_email(
        self,
        prepared: dict[str, Any],
    ) -> dict[str, Any]:
        ticket_id = str(prepared["ticketId"])
        template_id = str(prepared["templateId"])
        subject = str(prepared["subject"])
        recipients = [str(value) for value in prepared["recipients"]]
        sender = dict(prepared["sender"])
        expected_from_address = str(sender["address"])
        plan_material = "|".join(
            [
                ticket_id,
                template_id,
                subject,
                expected_from_address.casefold(),
                *sorted(recipient.casefold() for recipient in recipients),
            ]
        )
        plan_hash = hashlib.sha256(plan_material.encode("utf-8")).hexdigest()
        idempotency_key = f"credentials-347370:{plan_hash}"
        target = f"{ticket_id}:{template_id}:{plan_hash[:16]}"
        operation = "salesforce_ticket_company_credentials_email_send"
        with self._salesforce_operation(
            idempotency_key,
            operation,
            target,
            plan_hash,
            track_provider_attempt=True,
            reconcile_pending=lambda: self._reconcile_ticket_company_credentials_delivery(
                prepared,
                idempotency_key=idempotency_key,
            ),
        ) as prior:
            if prior is not None:
                return {
                    **_bounded_record(prior),
                    "sent": False,
                    "duplicate": True,
                    "replayed": True,
                    "writesPerformed": False,
                    "idempotencyKey": idempotency_key,
                }
            existing: dict[str, dict[str, Any]] = {}
            for recipient in recipients:
                match = self._matching_ticket_sensitive_email(
                    ticket_id,
                    recipient=recipient,
                    subject=subject,
                    expected_from_address=expected_from_address,
                )
                if match:
                    existing[recipient.casefold()] = match
            if len(existing) == len(recipients):
                receipt = {
                    **_public_sensitive_delivery_receipt(
                        prepared,
                        existing,
                        idempotency_key=idempotency_key,
                        sent=False,
                        duplicate=True,
                    ),
                    "replayed": False,
                    "writesPerformed": False,
                }
                self._complete_salesforce_operation(
                    idempotency_key,
                    operation,
                    target,
                    plan_hash,
                    receipt,
                )
                return receipt
            rendered_preview = dict(prepared["renderedPreview"])
            rendered_body = (
                str(rendered_preview.get("htmlBody") or "").strip()
                or str(rendered_preview.get("plainTextBody") or "").strip()
            )
            if not rendered_body:
                raise SalesforceUnavailableError(
                    "stored credentials template rendered no usable body"
                )
            missing = [
                recipient
                for recipient in recipients
                if recipient.casefold() not in existing
            ]
            inputs = [
                {
                    "emailAddresses": recipient,
                    "emailSubject": subject,
                    "emailBody": rendered_body,
                    "relatedRecordId": ticket_id,
                    "logEmailOnSend": True,
                    "senderType": str(sender["senderType"]),
                    "senderAddress": expected_from_address,
                }
                for recipient in missing
            ]
            self._mark_salesforce_provider_attempt(
                idempotency_key,
                operation,
                target,
                plan_hash,
            )
            provider_result = self._request(
                "POST",
                "/actions/standard/emailSimple",
                json={"inputs": inputs},
            )
            if not _email_action_succeeded(provider_result):
                raise SalesforceUnavailableError(
                    "Salesforce credentials email action was rejected "
                    f"({_email_action_error_codes(provider_result)}); no retry was attempted"
                )

            readback = dict(existing)
            for attempt in range(4):
                for recipient in recipients:
                    key = recipient.casefold()
                    if key in readback:
                        continue
                    match = self._matching_ticket_sensitive_email(
                        ticket_id,
                        recipient=recipient,
                        subject=subject,
                        expected_from_address=expected_from_address,
                    )
                    if match:
                        readback[key] = match
                if len(readback) == len(recipients):
                    break
                if attempt < 3:
                    time.sleep(0.5)
            if len(readback) != len(recipients):
                raise SalesforceUnavailableError(
                    "Salesforce accepted the credentials email action but complete "
                    "EmailMessage readback was not found; do not retry"
                )
            _require_email_readback_sender(readback.values(), expected_from_address)
            receipt = _public_sensitive_delivery_receipt(
                prepared,
                readback,
                idempotency_key=idempotency_key,
                sent=bool(missing),
                duplicate=not missing,
            )
            receipt["replayed"] = False
            receipt["writesPerformed"] = bool(missing)
            self._complete_salesforce_operation(
                idempotency_key,
                operation,
                target,
                plan_hash,
                receipt,
            )
            return receipt

    def _reconcile_ticket_company_credentials_delivery(
        self,
        prepared: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        """Recover ticket 347370 using only redacted delivery metadata."""

        ticket_id = str(prepared["ticketId"])
        subject = str(prepared["subject"])
        recipients = [str(value) for value in prepared["recipients"]]
        sender = dict(prepared["sender"])
        expected_from_address = str(sender["address"])
        readback: dict[str, dict[str, Any]] = {}
        for attempt in range(4):
            for recipient in recipients:
                key = recipient.casefold()
                if key in readback:
                    continue
                match = self._matching_ticket_sensitive_email(
                    ticket_id,
                    recipient=recipient,
                    subject=subject,
                    expected_from_address=expected_from_address,
                )
                if match:
                    readback[key] = match
            if len(readback) == len(recipients):
                break
            if attempt < 3:
                time.sleep(0.5)
        if len(readback) != len(recipients):
            return None
        _require_email_readback_sender(readback.values(), expected_from_address)
        return _public_sensitive_delivery_receipt(
            prepared,
            readback,
            idempotency_key=idempotency_key,
            sent=False,
            duplicate=True,
        )

    def send_ticket_email(
        self,
        *,
        ticket_id: str,
        subject: str,
        body: str,
        allowed_record_types: Collection[str] | None = None,
    ) -> dict[str, Any]:
        del ticket_id, subject, body, allowed_record_types
        raise SalesforceScopeError(
            "Freehand Salesforce ticket email is disabled. Use the approved template inventory, "
            "preview, and situation-based send operations."
        )

    def _prepare_ticket_template_email(
        self,
        *,
        ticket_id: str,
        situation: str,
        details: dict[str, Any] | None,
        lane: str,
        allowed_record_types: Collection[str] | None,
    ) -> dict[str, Any]:
        clean_ticket_id = _required_id(ticket_id, "ticket_id")
        self._assert_ticket_scope(clean_ticket_id, allowed_record_types)
        clean_lane = _required_email_lane(lane)
        clean_situation = str(situation or "").strip().casefold()
        spec = APPROVED_TICKET_EMAIL_SITUATIONS.get(clean_situation)
        if (
            not spec
            or spec.get("classification") != EMAIL_TEMPLATE_CLASS_APPROVED
            or spec.get("specialized")
        ):
            allowed = sorted(
                key
                for key, value in APPROVED_TICKET_EMAIL_SITUATIONS.items()
                if (
                    not value.get("specialized")
                    and value.get("classification") == EMAIL_TEMPLATE_CLASS_APPROVED
                    and clean_lane in tuple(value.get("owningLanes") or ())
                )
            )
            raise SalesforceScopeError(
                "situation must use a general approved ticket template: " + ", ".join(allowed)
            )
        self._assert_email_template_lane(spec, clean_lane)
        clean_details = dict(details or {})
        expected_fields = set(spec.get("detailFields") or ())
        if set(clean_details) != expected_fields:
            raise SalesforceScopeError(
                f"{clean_situation} details must contain exactly: "
                + (", ".join(sorted(expected_fields)) or "no fields")
            )

        ticket = self.read_ticket(clean_ticket_id)["record"]
        recipient_policy = str(spec.get("recipientPolicy") or "")
        if recipient_policy in {"account_primary_and_ticket_listed", "account_primary_only"}:
            targets = self._billing_confirmation_targets(ticket)
            if recipient_policy == "account_primary_only":
                targets = {
                    **targets,
                    "additionalRecipients": [],
                    "recipients": [str(targets["primaryRecipient"])],
                }
        else:
            targets = self._ticket_contact_template_targets(ticket)
        template = self._resolve_approved_email_template(
            clean_situation,
            lane=clean_lane,
        )
        sender = self._resolve_department_sender(str(spec["department"]))
        preview = self._render_stored_email_template(
            template_id=template["templateId"],
            recipient_id=targets["renderContactId"],
            related_record_id=clean_ticket_id,
        )
        preview = _normalize_agent_email_signature(
            preview,
            department=str(spec["department"]),
        )
        required_fragments = [
            str(value) for value in spec.get("requiredBodyFragments", ())
        ]
        customized = False
        if clean_situation == "billing_inquiry_update":
            account_id = _required_id(str(ticket.get("Account__c") or ""), "ticket account")
            account_result = self._query(
                "SELECT Id,Name FROM Account "
                f"WHERE Id = '{account_id}' LIMIT 1"
            )
            accounts = [
                dict(record)
                for record in account_result.get("records", [])
                if isinstance(record, dict)
            ]
            if len(accounts) != 1:
                raise SalesforceScopeError(
                    "billing inquiry template requires one verified ticket Account"
                )
            account_name = _bounded(accounts[0].get("Name"), "ticket Account name", 255)
            last4 = str(clean_details.get("last4Digits") or "").strip()
            if not re.fullmatch(r"\d{4}", last4):
                raise SalesforceScopeError("last4Digits must contain exactly four digits")
            message = _bounded(
                re.sub(r"\s+", " ", str(clean_details.get("message") or "")).strip(),
                "message",
                1200,
            )
            _validate_billing_inquiry_insert(
                message,
                account_name=account_name,
                last4=last4,
            )
            preview = _insert_billing_inquiry_details(
                preview,
                account_name=account_name,
                last4=last4,
                message=message,
            )
            required_fragments = [account_name, last4, message]
            customized = True
        elif clean_situation == "support_one_off_message":
            message = _bounded_support_one_off_message(clean_details.get("message"))
            preview = _insert_support_one_off_message(preview, message=message)
            required_fragments = [message]
            customized = True

        _verify_agent_email_signature(
            preview,
            required_signature=(
                "Nova Point of Sale Support"
                if clean_situation == "support_one_off_message"
                else None
            ),
        )

        preview_summary = _verify_approved_template_preview(
            preview,
            expected_subject=template["subject"],
            brand_template_id=template["brandTemplateId"],
            required_fragments=required_fragments,
        )
        if not required_fragments:
            required_fragments = _stable_template_fragments(
                str(preview.get("plainTextBody") or "")
            )
        if not required_fragments:
            raise SalesforceUnavailableError(
                "Approved template preview did not contain a stable duplicate-check fragment"
            )
        return {
            "ticketId": clean_ticket_id,
            "situation": clean_situation,
            "templateId": template["templateId"],
            "templateName": template["templateName"],
            "templateDeveloperName": template["templateDeveloperName"],
            "subject": template["subject"],
            "brandTemplateId": template["brandTemplateId"],
            "renderedPreview": preview,
            "previewSummary": preview_summary,
            "targets": targets,
            "sender": sender,
            "requiredFragments": required_fragments,
            "customized": customized,
        }

    @staticmethod
    def _assert_email_template_lane(spec: dict[str, Any], lane: str) -> None:
        owning_lanes = tuple(str(value) for value in spec.get("owningLanes") or ())
        if lane not in owning_lanes:
            raise SalesforceScopeError(
                "email situation is owned by a different department lane"
            )

    def email_sender_preflight(self) -> dict[str, Any]:
        """Inspect only the three server-owned Org-Wide Email policies.

        This is an inventory/readiness surface, not a sender selector. In
        particular, Darius appearing as ready here does not make a send route
        available: a direct-Darius reply must also pass exact inbound-message
        evidence and use a separately approved stored template.
        """

        policies = (
            (
                "support",
                SUPPORT_ORG_WIDE_EMAIL_ADDRESS,
                EMAIL_TEMPLATE_SENDER_POLICY,
                "approved_support_template_routes",
            ),
            (
                "billing",
                BILLING_ORG_WIDE_EMAIL_ADDRESS,
                EMAIL_TEMPLATE_SENDER_POLICY,
                "approved_billing_template_routes",
            ),
            (
                "direct_darius_reply",
                DARIUS_ORG_WIDE_EMAIL_ADDRESS,
                DIRECT_DARIUS_REPLY_SENDER_POLICY,
                "exact_inbound_emailmessage_reply_only",
            ),
        )
        senders: list[dict[str, Any]] = []
        for policy, address, sender_policy, allowed_use in policies:
            records = self._org_wide_email_address_records(address)
            unique = len(records) == 1
            record = records[0] if unique else {}
            address_matches = (
                str(record.get("Address") or "").strip().casefold()
                == address.casefold()
            )
            all_profiles = record.get("IsAllowAllProfiles") is True
            ready = unique and address_matches and all_profiles
            if not unique:
                reason = "required address did not resolve uniquely"
            elif not address_matches:
                reason = "resolved address did not match the fixed policy"
            elif not all_profiles:
                reason = "required address is not available to every executing profile"
            else:
                reason = "ready"
            senders.append(
                {
                    "policy": policy,
                    "address": address,
                    "senderPolicy": sender_policy,
                    "allowedUse": allowed_use,
                    "displayName": (
                        str(record.get("DisplayName") or "") if unique else ""
                    ),
                    "unique": unique,
                    "availableToAllProfiles": all_profiles,
                    "ready": ready,
                    "reason": reason,
                    "providerVerificationBoundary": (
                        "email_action_acceptance_and_emailmessage_from_address_readback"
                    ),
                    "proactiveAllowed": policy != "direct_darius_reply",
                }
            )
        return {
            "ok": True,
            "verified": True,
            "senders": senders,
            "count": len(senders),
            "allRequiredReady": all(sender["ready"] for sender in senders),
            "callerSelectedSenderAllowed": False,
            "readOnly": True,
            "writesPerformed": False,
        }

    def _resolve_department_sender(self, department: str) -> dict[str, str]:
        """Resolve one exact globally usable department Org-Wide Email Address.

        The typed OrgWideEmailAddress projection proves exact identity and
        all-profile availability, but does not expose a supported verification
        flag. Verification therefore remains provider-enforced: a send is
        accepted only when the email action succeeds, and completion additionally
        requires EmailMessage.FromAddress readback for every recipient.
        """

        clean_department = str(department or "").strip().casefold()
        expected_address = DEPARTMENT_ORG_WIDE_EMAIL_ADDRESSES.get(clean_department)
        if not expected_address:
            raise SalesforceScopeError("email department sender policy is not approved")
        return self._resolve_exact_org_wide_sender(
            policy=clean_department,
            expected_address=expected_address,
            sender_policy=EMAIL_TEMPLATE_SENDER_POLICY,
        )

    def _resolve_direct_darius_reply_sender(
        self,
        *,
        ticket_id: str,
        inbound_email_message_id: str,
        recipient: str,
        lane: str,
    ) -> dict[str, Any]:
        """Resolve Darius only for one exact customer reply on the same ticket.

        The recipient is not inferred from a ticket Contact or Account. It must
        equal the exact inbound EmailMessage FromAddress, while the inbound
        message itself must be addressed to Darius in ToAddress.
        """

        clean_lane = _required_email_lane(lane)
        if clean_lane != "direct_codex":
            raise SalesforceScopeError(
                "direct Darius reply sender is available only to the direct operator lane"
            )
        clean_ticket_id = _required_id(ticket_id, "ticket_id")
        clean_message_id = _required_id(
            inbound_email_message_id,
            "inbound_email_message_id",
        )
        clean_recipient = _canonical_single_mailbox(recipient)
        if not clean_recipient:
            raise SalesforceScopeError(
                "direct Darius reply recipient must be one exact email address"
            )
        result = self._query(
            "SELECT Id,RelatedToId,Incoming,FromAddress,ToAddress "
            "FROM EmailMessage "
            f"WHERE Id = '{clean_message_id}' LIMIT 2"
        )
        records = [
            dict(record)
            for record in result.get("records", [])
            if isinstance(record, dict)
        ]
        if len(records) != 1:
            raise SalesforceUnavailableError(
                "The exact inbound Salesforce EmailMessage did not resolve uniquely"
            )
        record = records[0]
        if str(record.get("Id") or "") != clean_message_id:
            raise SalesforceUnavailableError(
                "Resolved inbound Salesforce EmailMessage identity did not match"
            )
        if str(record.get("RelatedToId") or "") != clean_ticket_id:
            raise SalesforceScopeError(
                "inbound Salesforce EmailMessage is not related to the exact ticket"
            )
        if record.get("Incoming") is not True:
            raise SalesforceScopeError(
                "direct Darius sender requires an inbound Salesforce EmailMessage"
            )
        direct_recipients = _canonical_mailbox_list(
            record.get("ToAddress"),
            allow_semicolon_separator=True,
        )
        if DARIUS_ORG_WIDE_EMAIL_ADDRESS.casefold() not in direct_recipients:
            raise SalesforceScopeError(
                "inbound Salesforce EmailMessage was not addressed directly to Darius"
            )
        inbound_sender = _canonical_single_mailbox(record.get("FromAddress"))
        if (
            not inbound_sender
            or _is_nova_email_domain(inbound_sender)
        ):
            raise SalesforceScopeError(
                "inbound Salesforce EmailMessage does not contain one verified external sender"
            )
        if clean_recipient != inbound_sender:
            raise SalesforceScopeError(
                "direct Darius reply recipient must match the inbound EmailMessage sender"
            )
        sender = self._resolve_exact_org_wide_sender(
            policy="direct_darius_reply",
            expected_address=DARIUS_ORG_WIDE_EMAIL_ADDRESS,
            sender_policy=DIRECT_DARIUS_REPLY_SENDER_POLICY,
        )
        return {
            **sender,
            "inboundEmailMessageId": clean_message_id,
            "recipient": inbound_sender,
            "recipientSource": "inbound_emailmessage_from_address",
            "replyOnly": True,
        }

    def _org_wide_email_address_records(
        self,
        expected_address: str,
    ) -> list[dict[str, Any]]:
        result = self._query(
            "SELECT Id,Address,DisplayName,IsAllowAllProfiles "
            "FROM OrgWideEmailAddress "
            f"WHERE Address = '{_escape_soql(expected_address)}' LIMIT 2"
        )
        return [
            dict(record)
            for record in result.get("records", [])
            if isinstance(record, dict)
        ]

    def _resolve_exact_org_wide_sender(
        self,
        *,
        policy: str,
        expected_address: str,
        sender_policy: str,
    ) -> dict[str, str]:
        records = self._org_wide_email_address_records(expected_address)
        if len(records) != 1:
            raise SalesforceUnavailableError(
                f"The required {policy} Org-Wide Email Address did not resolve uniquely"
            )
        record = records[0]
        sender_id = _required_id(
            str(record.get("Id") or ""),
            f"{policy} Org-Wide Email Address id",
        )
        resolved_address = str(record.get("Address") or "").strip()
        if resolved_address.casefold() != expected_address.casefold():
            raise SalesforceUnavailableError(
                "Resolved Org-Wide Email Address did not match fixed sender policy"
            )
        if record.get("IsAllowAllProfiles") is not True:
            raise SalesforceUnavailableError(
                "Required Org-Wide Email Address is not available to every executing profile"
            )
        return {
            "department": policy,
            "orgWideEmailAddressId": sender_id,
            "address": expected_address,
            "senderType": "OrgWideEmailAddress",
            "senderPolicy": sender_policy,
            "providerVerificationBoundary": (
                "email_action_acceptance_and_emailmessage_from_address_readback"
            ),
        }

    def _resolve_approved_email_template(
        self,
        situation: str,
        *,
        lane: str,
        allow_specialized: bool = False,
    ) -> dict[str, str]:
        clean_situation = str(situation or "").strip().casefold()
        clean_lane = _required_email_lane(lane)
        spec = APPROVED_TICKET_EMAIL_SITUATIONS.get(clean_situation)
        if (
            not spec
            or spec.get("classification") != EMAIL_TEMPLATE_CLASS_APPROVED
            or (spec.get("specialized") and not allow_specialized)
        ):
            raise SalesforceScopeError("email situation is not available through this operation")
        self._assert_email_template_lane(spec, clean_lane)
        folder_id = str(spec["folderId"])
        name = str(spec["name"])
        developer_name = str(spec["developerName"])
        result = self._query(
            "SELECT Id,Name,DeveloperName,FolderId,TemplateType,IsActive,Subject,BrandTemplateId "
            "FROM EmailTemplate "
            f"WHERE FolderId = '{folder_id}' "
            f"AND DeveloperName = '{_escape_soql(developer_name)}' "
            "AND IsActive = true LIMIT 2"
        )
        records = [
            dict(record)
            for record in result.get("records", [])
            if isinstance(record, dict)
        ]
        if len(records) != 1:
            raise SalesforceUnavailableError(
                f"The approved {clean_situation} template did not resolve uniquely"
            )
        record = records[0]
        template_id = _required_id(
            str(record.get("Id") or ""),
            f"{clean_situation} template id",
        )
        brand_template_id = _required_id(
            str(record.get("BrandTemplateId") or ""),
            f"{clean_situation} brand template id",
        )
        if str(record.get("FolderId") or "")[:15] != folder_id:
            raise SalesforceUnavailableError("Approved email template folder did not match policy")
        template_subject = _bounded(
            str(record.get("Subject") or ""),
            "template subject",
            500,
        )
        if template_subject != str(spec["subject"]):
            raise SalesforceUnavailableError(
                "Approved email template subject did not match policy"
            )
        resolved_developer_name = str(record.get("DeveloperName") or "")
        if resolved_developer_name != developer_name:
            raise SalesforceUnavailableError(
                "Approved email template developer name did not match policy"
            )
        if str(record.get("Name") or "") != name:
            raise SalesforceUnavailableError(
                "Approved email template display name did not match policy"
            )
        expected_template_id = str(spec.get("expectedTemplateId") or "")
        if expected_template_id and template_id != expected_template_id:
            raise SalesforceUnavailableError(
                "Approved email template record identity did not match policy"
            )
        return {
            "templateId": template_id,
            "templateName": str(record.get("Name") or ""),
            "templateDeveloperName": resolved_developer_name,
            "subject": template_subject,
            "brandTemplateId": brand_template_id,
        }

    def _ticket_contact_template_targets(self, ticket: dict[str, Any]) -> dict[str, Any]:
        ticket_contact_id = _optional_id(
            str(ticket.get("Contact__c") or ""),
            "ticket contact",
        )
        if not ticket_contact_id:
            raise SalesforceScopeError(
                "Approved ticket email requires a verified Salesforce ticket Contact"
            )
        contact = self._request("GET", f"/sobjects/Contact/{ticket_contact_id}")
        recipient = str(contact.get("Email") or "").strip()
        if not EMAIL.fullmatch(recipient):
            raise SalesforceScopeError(
                "Verified Salesforce ticket Contact has no usable email"
            )
        return {
            "accountId": str(ticket.get("Account__c") or ""),
            "accountName": "",
            "primaryContactId": ticket_contact_id,
            "primaryRecipient": recipient,
            "primarySendContactId": ticket_contact_id,
            "renderContactId": ticket_contact_id,
            "additionalRecipients": [],
            "recipients": [recipient],
        }

    def _verified_ticket_attachment_ids(
        self,
        ticket_id: str,
        requested_ids: Sequence[str] | None,
    ) -> list[str]:
        """Return only ContentVersion ids that are verified attached to the ticket.

        A send must never carry a file that is not already a verified ticket
        attachment: each requested id must match a latest ContentVersion whose
        ContentDocumentLink points at this exact ticket.
        """
        if not requested_ids:
            return []
        wanted = [
            _required_id(str(value), "attachment_content_version_ids")
            for value in requested_ids
        ]
        linked = {
            str(record.get("Id") or "")
            for record in self._ticket_content_versions(ticket_id)
            if isinstance(record, dict)
        }
        verified: list[str] = []
        for value in wanted:
            if value in linked and value not in verified:
                verified.append(value)
            else:
                raise SalesforceScopeError(
                    f"attachment {value} is not a verified attachment on ticket {ticket_id}; "
                    "upload it to the ticket first"
                )
        return verified

    def _deliver_approved_ticket_template(
        self,
        prepared: dict[str, Any],
        *,
        mark_provider_attempt: Any | None = None,
    ) -> dict[str, Any]:
        ticket_id = str(prepared["ticketId"])
        subject = str(prepared["subject"])
        template_id = str(prepared["templateId"])
        preview = dict(prepared["renderedPreview"])
        targets = dict(prepared["targets"])
        sender = dict(prepared["sender"])
        expected_from_address = str(sender["address"])
        required_fragments = [str(value) for value in prepared["requiredFragments"]]
        recipients = [str(value) for value in targets["recipients"]]
        existing: dict[str, dict[str, Any]] = {}
        missing: list[str] = []
        for recipient in recipients:
            match = self._matching_ticket_template_email(
                ticket_id,
                recipient=recipient,
                subject=subject,
                required_fragments=required_fragments,
                expected_from_address=expected_from_address,
            )
            if match:
                existing[recipient.casefold()] = match
            else:
                missing.append(recipient)

        provider_result: Any = None
        if missing:
            rendered_body = (
                str(preview.get("htmlBody") or "").strip()
                or str(preview.get("plainTextBody") or "").strip()
            )
            if not rendered_body:
                raise SalesforceUnavailableError(
                    "Approved Salesforce template rendered no usable body"
                )
            # emailSimple treats emailBody as plain text unless sendRichBody
            # is set. The approved templates render HTML; without this flag the
            # raw markup lands in the customer's plain-text body (gibberish).
            inputs: list[dict[str, Any]] = []
            primary_recipient = str(targets["primaryRecipient"])
            primary_contact_id = str(targets["primarySendContactId"])
            attachment_ids = [
                str(value)
                for value in (prepared.get("attachmentContentVersionIds") or [])
            ]
            for recipient in missing:
                payload: dict[str, Any] = {
                    "relatedRecordId": ticket_id,
                    "logEmailOnSend": True,
                    "senderType": str(sender["senderType"]),
                    "senderAddress": expected_from_address,
                    "sendRichBody": bool(
                        re.search(
                            r"</?(?:html|body|table|div|img|br|p)\b",
                            rendered_body,
                            re.I,
                        )
                    ),
                }
                if attachment_ids:
                    payload["attachmentIdCollection"] = list(attachment_ids)
                if (
                    recipient.casefold() == primary_recipient.casefold()
                    and primary_contact_id
                ):
                    payload["recipientId"] = primary_contact_id
                else:
                    payload["emailAddresses"] = recipient
                payload["emailSubject"] = subject
                payload["emailBody"] = rendered_body
                inputs.append(payload)
            if mark_provider_attempt is not None:
                mark_provider_attempt()
            provider_result = self._request(
                "POST",
                "/actions/standard/emailSimple",
                json={"inputs": inputs},
            )
            if not _email_action_succeeded(provider_result):
                raise SalesforceUnavailableError(
                    "Salesforce approved-template email action was rejected "
                    f"({_email_action_error_codes(provider_result)}); no retry was attempted"
                )

        readback = dict(existing)
        for attempt in range(4):
            for recipient in recipients:
                key = recipient.casefold()
                if key in readback:
                    continue
                match = self._matching_ticket_template_email(
                    ticket_id,
                    recipient=recipient,
                    subject=subject,
                    required_fragments=required_fragments,
                    expected_from_address=expected_from_address,
                )
                if match:
                    readback[key] = match
            if len(readback) == len(recipients):
                break
            if attempt < 3:
                time.sleep(0.5)
        if len(readback) != len(recipients):
            raise SalesforceUnavailableError(
                "Salesforce accepted the approved-template email action but complete "
                "EmailMessage readback was not found; do not retry"
            )
        _require_email_readback_sender(readback.values(), expected_from_address)
        primary_record = readback[str(targets["primaryRecipient"]).casefold()]
        return {
            "ok": True,
            "accepted": True,
            "sent": bool(missing),
            "duplicate": not missing,
            "verified": True,
            "deliveryVerified": True,
            "ticketId": ticket_id,
            "accountId": targets["accountId"],
            "contactId": targets["primaryContactId"],
            "primaryRecipient": targets["primaryRecipient"],
            "additionalRecipients": targets["additionalRecipients"],
            "recipients": recipients,
            "department": sender["department"],
            "senderPolicy": sender["senderPolicy"],
            "fromAddress": expected_from_address,
            "emailMessage": _public_email_record(primary_record),
            "emailMessages": [
                _public_email_record(readback[recipient.casefold()])
                for recipient in recipients
            ],
            "providerResult": (
                _bounded_record(provider_result)
                if provider_result is not None
                else None
            ),
        }

    def _reconcile_approved_ticket_template_delivery(
        self,
        prepared: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Recover an uncertain approved-template send from authoritative EmailMessage rows.

        This method is deliberately read-only.  A pending journal entry may only
        become accepted after every exact recipient/subject/body/sender match is
        visible on the same Salesforce surface used by normal post-send readback.
        """

        ticket_id = str(prepared["ticketId"])
        subject = str(prepared["subject"])
        targets = dict(prepared["targets"])
        sender = dict(prepared["sender"])
        expected_from_address = str(sender["address"])
        required_fragments = [
            str(value) for value in prepared["requiredFragments"]
        ]
        recipients = [str(value) for value in targets["recipients"]]
        readback: dict[str, dict[str, Any]] = {}
        for attempt in range(4):
            for recipient in recipients:
                key = recipient.casefold()
                if key in readback:
                    continue
                match = self._matching_ticket_template_email(
                    ticket_id,
                    recipient=recipient,
                    subject=subject,
                    required_fragments=required_fragments,
                    expected_from_address=expected_from_address,
                )
                if match:
                    readback[key] = match
            if len(readback) == len(recipients):
                break
            if attempt < 3:
                time.sleep(0.5)
        if len(readback) != len(recipients):
            return None
        _require_email_readback_sender(readback.values(), expected_from_address)
        primary_record = readback[str(targets["primaryRecipient"]).casefold()]
        return {
            "ok": True,
            "accepted": True,
            "sent": False,
            "duplicate": True,
            "verified": True,
            "deliveryVerified": True,
            "recoveredFromEmailMessageReadback": True,
            "ticketId": ticket_id,
            "accountId": targets["accountId"],
            "contactId": targets["primaryContactId"],
            "primaryRecipient": targets["primaryRecipient"],
            "additionalRecipients": targets["additionalRecipients"],
            "recipients": recipients,
            "department": sender["department"],
            "senderPolicy": sender["senderPolicy"],
            "fromAddress": expected_from_address,
            "emailMessage": _public_email_record(primary_record),
            "emailMessages": [
                _public_email_record(readback[recipient.casefold()])
                for recipient in recipients
            ],
            "providerResult": None,
        }

    def send_ticket_credit_confirmation_email(
        self,
        *,
        ticket_id: str,
        credit_amount_cents: int,
        allowed_record_types: Collection[str] | None = None,
    ) -> dict[str, Any]:
        """Send the approved credit template to the Account primary recipient and ticket-listed emails."""

        clean_ticket_id = _required_id(ticket_id, "ticket_id")
        if (
            isinstance(credit_amount_cents, bool)
            or not isinstance(credit_amount_cents, int)
            or credit_amount_cents < 1
            or credit_amount_cents > 100_000_000
        ):
            raise SalesforceScopeError("credit_amount_cents must be an integer between 1 and 100000000")
        expected_amount = _currency_from_cents(credit_amount_cents)
        self._assert_ticket_scope(clean_ticket_id, allowed_record_types)
        ticket = self.read_ticket(clean_ticket_id)["record"]
        ticket_credit_cents = _decimal_currency_field_to_cents(ticket.get("Credit_Amount__c"))
        if ticket_credit_cents != credit_amount_cents:
            raise SalesforceScopeError(
                "Salesforce Credit_Amount__c must match the verified Maxio credit before email send"
            )
        targets = self._billing_confirmation_targets(ticket)
        template = self._resolve_approved_email_template(
            "credit_applied",
            lane="billing_agent",
            allow_specialized=True,
        )
        sender = self._resolve_department_sender("billing")

        preview = self._render_stored_email_template(
            template_id=template["templateId"],
            recipient_id=targets["renderContactId"],
            related_record_id=clean_ticket_id,
        )
        preview = _normalize_agent_email_signature(preview, department="billing")
        preview_summary = _verify_credit_template_preview(
            preview,
            expected_amount=expected_amount,
            brand_template_id=template["brandTemplateId"],
        )
        delivery = self._send_billing_confirmation_template(
            ticket_id=clean_ticket_id,
            template_id=template["templateId"],
            template_subject=template["subject"],
            rendered_preview=preview,
            expected_amount=expected_amount,
            targets=targets,
            sender=sender,
            label="credit",
        )
        return {
            **delivery,
            "templateDeveloperName": CREDIT_APPLIED_TEMPLATE_DEVELOPER_NAME,
            "creditAmount": expected_amount,
            "templatePreview": preview_summary,
        }

    def send_ticket_refund_confirmation_email(
        self,
        *,
        ticket_id: str,
        refund_amount_cents: int,
        allowed_record_types: Collection[str] | None = None,
    ) -> dict[str, Any]:
        """Send the approved refund template to the Account primary recipient and ticket-listed emails."""

        clean_ticket_id = _required_id(ticket_id, "ticket_id")
        if (
            isinstance(refund_amount_cents, bool)
            or not isinstance(refund_amount_cents, int)
            or refund_amount_cents < 1
            or refund_amount_cents > 100_000_000
        ):
            raise SalesforceScopeError("refund_amount_cents must be an integer between 1 and 100000000")
        expected_amount = _currency_from_cents(refund_amount_cents)
        self._assert_ticket_scope(clean_ticket_id, allowed_record_types)
        ticket = self.read_ticket(clean_ticket_id)["record"]
        targets = self._billing_confirmation_targets(ticket)
        template = self._resolve_approved_email_template(
            "refund_submitted",
            lane="billing_agent",
            allow_specialized=True,
        )
        sender = self._resolve_department_sender("billing")

        preview = self._render_stored_email_template(
            template_id=template["templateId"],
            recipient_id=targets["renderContactId"],
            related_record_id=clean_ticket_id,
        )
        preview = _normalize_agent_email_signature(preview, department="billing")
        preview_summary = _verify_refund_template_preview(
            preview,
            expected_amount=expected_amount,
            brand_template_id=template["brandTemplateId"],
        )

        delivery = self._send_billing_confirmation_template(
            ticket_id=clean_ticket_id,
            template_id=template["templateId"],
            template_subject=template["subject"],
            rendered_preview=preview,
            expected_amount=expected_amount,
            targets=targets,
            sender=sender,
            label="refund",
        )
        return {
            **delivery,
            "templateDeveloperName": REFUND_SUBMITTED_TEMPLATE_DEVELOPER_NAME,
            "refundAmount": expected_amount,
            "templatePreview": preview_summary,
        }

    def _account_cancellation_render_contact(
        self,
        account_id: str,
        ticket_id: str,
        current_render_contact_id: str,
    ) -> str:
        """Return a contact on the account being closed for template rendering.

        The account-cancellation email template merges {!Account.Name} from the
        recipient (whoId) contact's Account. When the Account primary contact
        belongs to a different account than the one being closed (common when a
        DBA differs from the Salesforce account name), that merge renders the
        wrong account name. Prefer a contact whose Account matches the account
        being closed (the ticket contact, else the account's primary), and fall
        back to the current render contact only when none is available.
        """
        clean_account_id = _required_id(account_id, "account_id")
        ticket_id = _required_id(ticket_id, "ticket_id")
        candidates: list[str] = []
        ticket = self.read_ticket(ticket_id)["record"]
        ticket_contact = str(ticket.get("Contact__c") or "").strip()
        if ticket_contact:
            candidates.append(ticket_contact)
        account = self._query(
            "SELECT Id, PrimaryContact__c FROM Account WHERE Id = '" + clean_account_id + "' LIMIT 1"
        ).get("records", [])
        if account:
            primary = str(account[0].get("PrimaryContact__c") or "").strip()
            if primary:
                candidates.append(primary)
        for contact_id in candidates:
            if not contact_id:
                continue
            rows = self._query(
                "SELECT Id, AccountId FROM Contact WHERE Id = '" + contact_id + "' LIMIT 1"
            ).get("records", [])
            if rows and str(rows[0].get("AccountId") or "") == clean_account_id:
                return str(rows[0].get("Id") or "")
        return current_render_contact_id

    def _billing_confirmation_targets(self, ticket: dict[str, Any]) -> dict[str, Any]:
        """Resolve a fixed primary Account recipient plus customer emails already present on the ticket."""

        account_id = _required_id(str(ticket.get("Account__c") or ""), "ticket account")
        account_result = self._query(
            "SELECT Id,Name,Email_Address__c,PrimaryContact__c,"
            "PrimaryContact__r.Id,PrimaryContact__r.Name,PrimaryContact__r.Email "
            f"FROM Account WHERE Id = '{account_id}' LIMIT 1"
        )
        accounts = [
            dict(record)
            for record in account_result.get("records", [])
            if isinstance(record, dict)
        ]
        if len(accounts) != 1:
            raise SalesforceScopeError("ticket Account did not resolve to exactly one Salesforce Account")
        account = accounts[0]
        primary = account.get("PrimaryContact__r")
        primary = dict(primary) if isinstance(primary, dict) else {}
        primary_contact_id = _optional_id(
            str(primary.get("Id") or account.get("PrimaryContact__c") or ""),
            "Account primary Contact",
        )
        primary_contact_email = str(primary.get("Email") or "").strip()
        account_email = str(account.get("Email_Address__c") or "").strip()
        if primary_contact_id and EMAIL.fullmatch(primary_contact_email):
            primary_recipient = primary_contact_email
            primary_send_contact_id = primary_contact_id
        elif EMAIL.fullmatch(account_email):
            primary_recipient = account_email
            primary_send_contact_id = ""
        else:
            raise SalesforceScopeError(
                "Account primary Contact and Account Email Address have no usable customer email"
            )
        render_contact_id = primary_contact_id or _optional_id(
            str(ticket.get("Contact__c") or ""),
            "ticket contact",
        )
        if not render_contact_id:
            raise SalesforceScopeError(
                "billing confirmation template requires an Account primary Contact or ticket Contact"
            )
        additional = _verified_ticket_additional_emails(
            ticket,
            exclude={primary_recipient},
        )
        return {
            "accountId": account_id,
            "accountName": str(account.get("Name") or ""),
            "primaryContactId": primary_contact_id or "",
            "primaryRecipient": primary_recipient,
            "primarySendContactId": primary_send_contact_id,
            "renderContactId": render_contact_id,
            "additionalRecipients": additional,
            "recipients": [primary_recipient, *additional],
        }

    def _send_billing_confirmation_template(
        self,
        *,
        ticket_id: str,
        template_id: str,
        template_subject: str,
        rendered_preview: dict[str, str],
        expected_amount: str,
        targets: dict[str, Any],
        sender: dict[str, str],
        label: str,
    ) -> dict[str, Any]:
        clean_label = str(label or "").strip().casefold()
        if clean_label not in {"credit", "refund"}:
            raise SalesforceScopeError(
                "billing confirmation label must be credit or refund"
            )
        recipients = [str(value) for value in targets["recipients"]]
        preview_identity = {
            field: hashlib.sha256(
                str(rendered_preview.get(field) or "").encode("utf-8")
            ).hexdigest()
            for field in ("htmlBody", "plainTextBody")
        }
        plan_material = json.dumps(
            {
                "ticketId": ticket_id,
                "templateId": template_id,
                "subject": template_subject,
                "label": clean_label,
                "expectedAmount": expected_amount,
                "fromAddress": str(sender["address"]).casefold(),
                "recipients": sorted(
                    recipient.casefold() for recipient in recipients
                ),
                "preview": preview_identity,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        plan_hash = hashlib.sha256(plan_material.encode("utf-8")).hexdigest()
        idempotency_key = (
            f"ticket-{clean_label}-confirmation-email:{plan_hash}"
        )
        target = f"{ticket_id}:{template_id}:{plan_hash[:16]}"
        operation = (
            f"salesforce_ticket_{clean_label}_confirmation_email_send"
        )
        with self._salesforce_operation(
            idempotency_key,
            operation,
            target,
            plan_hash,
            track_provider_attempt=True,
            reconcile_pending=lambda: self._reconcile_billing_confirmation_delivery(
                ticket_id=ticket_id,
                template_subject=template_subject,
                expected_amount=expected_amount,
                targets=targets,
                sender=sender,
            ),
        ) as prior:
            if prior is not None:
                return {
                    **prior,
                    "sent": False,
                    "duplicate": True,
                    "replayed": True,
                    "writesPerformed": False,
                    "providerResult": None,
                    "idempotencyKey": idempotency_key,
                }
            delivery = {
                **self._deliver_billing_confirmation_template(
                    ticket_id=ticket_id,
                    template_id=template_id,
                    template_subject=template_subject,
                    rendered_preview=rendered_preview,
                    expected_amount=expected_amount,
                    targets=targets,
                    sender=sender,
                    label=clean_label,
                    mark_provider_attempt=lambda: self._mark_salesforce_provider_attempt(
                        idempotency_key,
                        operation,
                        target,
                        plan_hash,
                    ),
                ),
                "replayed": False,
                "idempotencyKey": idempotency_key,
            }
            delivery["writesPerformed"] = bool(delivery.get("sent"))
            self._complete_salesforce_operation(
                idempotency_key,
                operation,
                target,
                plan_hash,
                delivery,
            )
            return delivery

    def _deliver_billing_confirmation_template(
        self,
        *,
        ticket_id: str,
        template_id: str,
        template_subject: str,
        rendered_preview: dict[str, str],
        expected_amount: str,
        targets: dict[str, Any],
        sender: dict[str, str],
        label: str,
        mark_provider_attempt: Any | None = None,
    ) -> dict[str, Any]:
        recipients = [str(value) for value in targets["recipients"]]
        expected_from_address = str(sender["address"])
        existing: dict[str, dict[str, Any]] = {}
        missing: list[str] = []
        for recipient in recipients:
            match = self._matching_ticket_refund_confirmation(
                ticket_id,
                recipient=recipient,
                subject=template_subject,
                expected_amount=expected_amount,
                expected_from_address=expected_from_address,
            )
            if match:
                existing[recipient.casefold()] = match
            else:
                missing.append(recipient)

        provider_result: Any = None
        if missing:
            inputs: list[dict[str, Any]] = []
            primary_recipient = str(targets["primaryRecipient"])
            primary_contact_id = str(targets["primarySendContactId"])
            rendered_body = (
                str(rendered_preview.get("htmlBody") or "").strip()
                or str(rendered_preview.get("plainTextBody") or "").strip()
            )
            if not rendered_body:
                raise SalesforceUnavailableError("stored billing template rendered no usable body")
            for recipient in missing:
                payload: dict[str, Any] = {
                    "relatedRecordId": ticket_id,
                    "logEmailOnSend": True,
                    "senderType": str(sender["senderType"]),
                    "senderAddress": expected_from_address,
                }
                if (
                    recipient.casefold() == primary_recipient.casefold()
                    and primary_contact_id
                ):
                    payload["recipientId"] = primary_contact_id
                else:
                    payload["emailAddresses"] = recipient
                payload["emailSubject"] = template_subject
                payload["emailBody"] = rendered_body
                inputs.append(payload)
            if mark_provider_attempt is not None:
                mark_provider_attempt()
            provider_result = self._request(
                "POST",
                "/actions/standard/emailSimple",
                json={"inputs": inputs},
            )
            if not _email_action_succeeded(provider_result):
                raise SalesforceUnavailableError(
                    f"Salesforce {label} email action was rejected "
                    f"({_email_action_error_codes(provider_result)}); no retry was attempted"
                )

        readback = dict(existing)
        for attempt in range(4):
            for recipient in recipients:
                key = recipient.casefold()
                if key in readback:
                    continue
                match = self._matching_ticket_refund_confirmation(
                    ticket_id,
                    recipient=recipient,
                    subject=template_subject,
                    expected_amount=expected_amount,
                    expected_from_address=expected_from_address,
                )
                if match:
                    readback[key] = match
            if len(readback) == len(recipients):
                break
            if attempt < 3:
                time.sleep(0.5)
        if len(readback) != len(recipients):
            raise SalesforceUnavailableError(
                f"Salesforce accepted the {label} email action but complete EmailMessage readback "
                "was not found; do not retry"
            )
        _require_email_readback_sender(readback.values(), expected_from_address)
        primary_record = readback[str(targets["primaryRecipient"]).casefold()]
        return {
            "ok": True,
            "accepted": True,
            "sent": bool(missing),
            "duplicate": not missing,
            "ticketId": ticket_id,
            "accountId": targets["accountId"],
            "accountName": targets["accountName"],
            "contactId": targets["primaryContactId"],
            "primaryContactId": targets["primaryContactId"],
            "recipient": targets["primaryRecipient"],
            "primaryRecipient": targets["primaryRecipient"],
            "additionalRecipients": targets["additionalRecipients"],
            "recipients": recipients,
            "department": sender["department"],
            "senderPolicy": sender["senderPolicy"],
            "fromAddress": expected_from_address,
            "emailMessage": _public_email_record(primary_record),
            "emailMessages": [
                _public_email_record(readback[recipient.casefold()])
                for recipient in recipients
            ],
            "providerResult": _bounded_record(provider_result),
            "deliveryVerified": True,
            "callerSelectedRecipients": False,
        }

    def _reconcile_billing_confirmation_delivery(
        self,
        *,
        ticket_id: str,
        template_subject: str,
        expected_amount: str,
        targets: dict[str, Any],
        sender: dict[str, str],
    ) -> dict[str, Any] | None:
        """Recover an uncertain credit/refund send without calling the send action."""

        recipients = [str(value) for value in targets["recipients"]]
        expected_from_address = str(sender["address"])
        readback: dict[str, dict[str, Any]] = {}
        for attempt in range(4):
            for recipient in recipients:
                key = recipient.casefold()
                if key in readback:
                    continue
                match = self._matching_ticket_refund_confirmation(
                    ticket_id,
                    recipient=recipient,
                    subject=template_subject,
                    expected_amount=expected_amount,
                    expected_from_address=expected_from_address,
                )
                if match:
                    readback[key] = match
            if len(readback) == len(recipients):
                break
            if attempt < 3:
                time.sleep(0.5)
        if len(readback) != len(recipients):
            return None
        _require_email_readback_sender(readback.values(), expected_from_address)
        primary_record = readback[str(targets["primaryRecipient"]).casefold()]
        return {
            "ok": True,
            "accepted": True,
            "sent": False,
            "duplicate": True,
            "ticketId": ticket_id,
            "accountId": targets["accountId"],
            "accountName": targets["accountName"],
            "contactId": targets["primaryContactId"],
            "primaryContactId": targets["primaryContactId"],
            "recipient": targets["primaryRecipient"],
            "primaryRecipient": targets["primaryRecipient"],
            "additionalRecipients": targets["additionalRecipients"],
            "recipients": recipients,
            "department": sender["department"],
            "senderPolicy": sender["senderPolicy"],
            "fromAddress": expected_from_address,
            "emailMessage": _public_email_record(primary_record),
            "emailMessages": [
                _public_email_record(readback[recipient.casefold()])
                for recipient in recipients
            ],
            "providerResult": None,
            "deliveryVerified": True,
            "recoveredFromEmailMessageReadback": True,
            "callerSelectedRecipients": False,
        }

    def _render_stored_email_template(
        self,
        *,
        template_id: str,
        recipient_id: str,
        related_record_id: str,
    ) -> dict[str, str]:
        """Render a stored template through Salesforce without sending it."""

        clean_template_id = _required_id(template_id, "template_id")
        clean_recipient_id = _required_id(recipient_id, "recipient_id")
        clean_related_id = _required_id(related_record_id, "related_record_id")
        token, instance = self._authenticate()
        envelope = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:urn="urn:partner.soap.sforce.com">'
            '<soapenv:Header><urn:SessionHeader><urn:sessionId>'
            f"{escape_xml(token)}"
            "</urn:sessionId></urn:SessionHeader></soapenv:Header>"
            "<soapenv:Body><urn:renderStoredEmailTemplate><urn:renderRequest>"
            "<urn:attachmentRetrievalOption>NONE</urn:attachmentRetrievalOption>"
            f"<urn:templateId>{escape_xml(clean_template_id)}</urn:templateId>"
            "<urn:updateTemplateUsage>false</urn:updateTemplateUsage>"
            f"<urn:whatId>{escape_xml(clean_related_id)}</urn:whatId>"
            f"<urn:whoId>{escape_xml(clean_recipient_id)}</urn:whoId>"
            "</urn:renderRequest></urn:renderStoredEmailTemplate></soapenv:Body>"
            "</soapenv:Envelope>"
        )
        response = self.session.post(
            f"{instance}/services/Soap/u/{self.settings.api_version}",
            data=envelope.encode("utf-8"),
            headers={
                "Content-Type": "text/xml; charset=UTF-8",
                "SOAPAction": "renderStoredEmailTemplate",
            },
            timeout=30,
        )
        if response.status_code != 200:
            raise SalesforceUnavailableError(
                f"Salesforce stored-template preview failed with status {response.status_code}"
            )
        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError as exc:
            raise SalesforceUnavailableError("Salesforce stored-template preview returned invalid XML") from exc

        values: dict[str, list[str]] = {}
        for element in root.iter():
            local_name = element.tag.rsplit("}", 1)[-1]
            if element.text:
                values.setdefault(local_name, []).append(element.text)
        if not values.get("success") or values["success"][-1].strip().lower() != "true":
            codes = ",".join(values.get("statusCode", [])) or "RENDER_FAILED"
            raise SalesforceUnavailableError(
                f"Salesforce stored-template preview was rejected ({codes})"
            )
        return {
            "subject": (values.get("subject") or [""])[-1],
            "htmlBody": (values.get("htmlBody") or [""])[-1],
            "plainTextBody": (values.get("plainTextBody") or [""])[-1],
        }

    def read_ticket_email_log(self, ticket_id: str, *, limit: int = 10) -> dict[str, Any]:
        """Read bounded outbound EmailMessage receipts for one exact ticket."""

        clean_id = _required_id(ticket_id, "ticket_id")
        clean_limit = max(1, min(int(limit), 20))
        records = self._ticket_email_records(clean_id, limit=clean_limit)
        return {
            "ok": True,
            "ticketId": clean_id,
            "records": [_public_email_record(record) for record in records],
            "count": len(records),
        }

    def _matching_ticket_email(
        self,
        ticket_id: str,
        *,
        recipient: str,
        subject: str,
        body: str,
    ) -> dict[str, Any] | None:
        expected_recipient = recipient.strip().casefold()
        expected_subject = _normalized_text(subject)
        expected_body = _normalized_text(body)
        for record in self._ticket_email_records(ticket_id, limit=20, include_body=True):
            if record.get("Incoming") is True:
                continue
            recipients = {
                value.strip().casefold()
                for value in re.split(r"[,;]", str(record.get("ToAddress") or ""))
                if value.strip()
            }
            if expected_recipient not in recipients:
                continue
            if _normalized_text(str(record.get("Subject") or "")) != expected_subject:
                continue
            recorded_body = str(record.get("TextBody") or record.get("HtmlBody") or "")
            if _normalized_text(recorded_body) == expected_body:
                return record
        return None

    def _matching_ticket_email_subject(
        self,
        ticket_id: str,
        *,
        recipient: str,
        subject: str,
    ) -> dict[str, Any] | None:
        expected_recipient = recipient.strip().casefold()
        expected_subject = _normalized_text(subject)
        for record in self._ticket_email_records(ticket_id, limit=20):
            if record.get("Incoming") is True:
                continue
            recipients = {
                value.strip().casefold()
                for value in re.split(r"[,;]", str(record.get("ToAddress") or ""))
                if value.strip()
            }
            if expected_recipient not in recipients:
                continue
            if _normalized_text(str(record.get("Subject") or "")) == expected_subject:
                return record
        return None

    def _matching_ticket_template_email(
        self,
        ticket_id: str,
        *,
        recipient: str,
        subject: str,
        required_fragments: Collection[str],
        expected_from_address: str,
    ) -> dict[str, Any] | None:
        expected_recipient = recipient.strip().casefold()
        expected_subject = _normalized_text(subject)
        expected_sender = expected_from_address.strip().casefold()
        expected_fragments = [
            _normalized_text(fragment)
            for fragment in required_fragments
            if _normalized_text(fragment)
        ]
        if not expected_fragments:
            raise SalesforceScopeError(
                "approved template duplicate check requires at least one content fragment"
            )
        for record in self._ticket_email_records(ticket_id, limit=20, include_body=True):
            if record.get("Incoming") is True:
                continue
            if str(record.get("Status") or "") != "3":
                continue
            if str(record.get("FromAddress") or "").strip().casefold() != expected_sender:
                continue
            recipients = {
                value.strip().casefold()
                for value in re.split(r"[,;]", str(record.get("ToAddress") or ""))
                if value.strip()
            }
            if recipients != {expected_recipient}:
                continue
            if _normalized_text(str(record.get("Subject") or "")) != expected_subject:
                continue
            recorded_body = _normalized_email_body(
                str(record.get("TextBody") or record.get("HtmlBody") or "")
            )
            if all(fragment in recorded_body for fragment in expected_fragments):
                return record
        return None

    def _matching_ticket_refund_confirmation(
        self,
        ticket_id: str,
        *,
        recipient: str,
        subject: str,
        expected_amount: str,
        expected_from_address: str,
    ) -> dict[str, Any] | None:
        expected_recipient = recipient.strip().casefold()
        expected_subject = _normalized_text(subject)
        expected_sender = expected_from_address.strip().casefold()
        for record in self._ticket_email_records(ticket_id, limit=20, include_body=True):
            if record.get("Incoming") is True:
                continue
            if str(record.get("Status") or "") != "3":
                continue
            if str(record.get("FromAddress") or "").strip().casefold() != expected_sender:
                continue
            recipients = {
                value.strip().casefold()
                for value in re.split(r"[,;]", str(record.get("ToAddress") or ""))
                if value.strip()
            }
            if recipients != {expected_recipient}:
                continue
            if _normalized_text(str(record.get("Subject") or "")) != expected_subject:
                continue
            recorded_body = str(record.get("TextBody") or record.get("HtmlBody") or "")
            if expected_amount in recorded_body:
                return record
        return None

    def _matching_ticket_sensitive_email(
        self,
        ticket_id: str,
        *,
        recipient: str,
        subject: str,
        expected_from_address: str,
    ) -> dict[str, Any] | None:
        """Match only non-secret delivery metadata for the fixed credentials route."""

        expected_recipient = recipient.strip().casefold()
        expected_subject = _normalized_text(subject)
        expected_sender = expected_from_address.strip().casefold()
        for record in self._ticket_email_records(ticket_id, limit=20):
            if record.get("Incoming") is True:
                continue
            if str(record.get("Status") or "") != "3":
                continue
            if str(record.get("FromAddress") or "").strip().casefold() != expected_sender:
                continue
            recipients = {
                value.strip().casefold()
                for value in re.split(r"[,;]", str(record.get("ToAddress") or ""))
                if value.strip()
            }
            if recipients != {expected_recipient}:
                continue
            if _normalized_text(str(record.get("Subject") or "")) == expected_subject:
                return record
        return None

    def _ticket_email_records(
        self,
        ticket_id: str,
        *,
        limit: int,
        include_body: bool = False,
    ) -> list[dict[str, Any]]:
        clean_id = _required_id(ticket_id, "ticket_id")
        clean_limit = max(1, min(int(limit), 20))
        fields = "Id,Subject,ToAddress,Status,MessageDate,RelatedToId,FromAddress,CreatedDate,Incoming"
        if include_body:
            fields += ",TextBody,HtmlBody"
        result = self._query(
            f"SELECT {fields} FROM EmailMessage WHERE RelatedToId = '{clean_id}' "
            f"ORDER BY CreatedDate DESC LIMIT {clean_limit}"
        )
        return [record for record in result.get("records", []) if isinstance(record, dict)][:clean_limit]

    @contextmanager
    def _salesforce_write_lock(self) -> Iterator[None]:
        """Serialize one guarded Salesforce decision across threads and processes."""

        journal = self.settings.journal_path
        journal.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = Path(f"{journal}.lock")
        descriptor = os.open(
            lock_path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        with (
            SALESFORCE_OPERATION_LOCK,
            os.fdopen(descriptor, "a", encoding="utf-8") as handle,
        ):
            try:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def _salesforce_operation(
        self,
        key: str,
        operation: str,
        target: str,
        plan_hash: str,
        *,
        track_provider_attempt: bool = False,
        reconcile_pending: Any | None = None,
    ) -> Iterator[dict[str, Any] | None]:
        """Serialize guarded writes and reconcile uncertain sends before any retry.

        ``reconcile_pending`` must be a read-only authoritative readback.  It may
        return verified evidence to close a pending operation, but a missing
        match always remains fail-closed and never re-enters the provider write.
        """

        clean_key = _required_idempotency_key(key)
        clean_operation = _bounded(operation, "operation", 100)
        clean_target = _bounded(target, "target", 200)
        clean_hash = _required_preview_hash(plan_hash)
        journal = self.settings.journal_path
        journal.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = Path(f"{journal}.lock")
        descriptor = os.open(lock_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        with SALESFORCE_OPERATION_LOCK, os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            try:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                prior = self._prior_salesforce_operation(clean_key)
                if prior is not None:
                    if any(
                        prior.get(field) != expected
                        for field, expected in (
                            ("operation", clean_operation),
                            ("target", clean_target),
                            ("planHash", clean_hash),
                        )
                    ):
                        raise SalesforceScopeError(
                            "idempotency_key was already used for a different Salesforce operation"
                        )
                    if prior.get("status") in {"pending", "uncertain"}:
                        prior_evidence = prior.get("evidence")
                        if (
                            track_provider_attempt
                            and isinstance(prior_evidence, dict)
                            and prior_evidence.get("providerAttempted") is False
                        ):
                            # The prior process failed during its authoritative
                            # precheck, before the durable provider-attempt
                            # marker.  It is safe to run that exact precheck
                            # again while retaining the same serialized lock.
                            yield None
                            return
                        if reconcile_pending is None:
                            raise SalesforceScopeError(
                                "idempotency_key has an uncertain pending outcome; "
                                "read back the Salesforce target before any retry"
                            )
                        recovered = reconcile_pending()
                        if recovered is None:
                            raise SalesforceUnavailableError(
                                "Salesforce operation has an uncertain pending outcome and "
                                "authoritative EmailMessage readback is not yet complete; "
                                "no send retry was attempted"
                            )
                        if not isinstance(recovered, dict):
                            raise SalesforceUnavailableError(
                                "Salesforce pending-operation readback returned invalid evidence; "
                                "no send retry was attempted"
                            )
                        recovered_evidence = {
                            **recovered,
                            "sent": False,
                            "duplicate": True,
                            "replayed": True,
                            "writesPerformed": False,
                            "recoveredFromEmailMessageReadback": True,
                        }
                        for field in (
                            "internalRequestLocalDate",
                            "firstMessageGreetingIncluded",
                        ):
                            if field in prior_evidence:
                                recovered_evidence[field] = prior_evidence[field]
                        self._complete_salesforce_operation(
                            clean_key,
                            clean_operation,
                            clean_target,
                            clean_hash,
                            recovered_evidence,
                        )
                        yield recovered_evidence
                        return
                    evidence = prior.get("evidence")
                    yield dict(evidence) if isinstance(evidence, dict) else {
                        "ok": prior.get("status") == "accepted",
                        "verified": prior.get("status") == "accepted",
                    }
                    return
                self._journal_salesforce_operation(
                    "pending",
                    clean_key,
                    clean_operation,
                    clean_target,
                    clean_hash,
                    (
                        {"providerAttempted": False}
                        if track_provider_attempt
                        else {}
                    ),
                )
                yield None
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _mark_salesforce_provider_attempt(
        self,
        key: str,
        operation: str,
        target: str,
        plan_hash: str,
        *,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        """Durably mark the last safe point immediately before a provider write."""

        clean_key = _required_idempotency_key(key)
        clean_operation = _bounded(operation, "operation", 100)
        clean_target = _bounded(target, "target", 200)
        clean_hash = _required_preview_hash(plan_hash)
        prior = self._prior_salesforce_operation(clean_key)
        if (
            prior is None
            or prior.get("status") != "pending"
            or any(
                prior.get(field) != expected
                for field, expected in (
                    ("operation", clean_operation),
                    ("target", clean_target),
                    ("planHash", clean_hash),
                )
            )
        ):
            raise SalesforceUnavailableError(
                "Salesforce provider attempt was not protected by the expected pending journal; "
                "the write was not attempted"
            )
        self._journal_salesforce_operation(
            "pending",
            clean_key,
            clean_operation,
            clean_target,
            clean_hash,
            {
                "providerAttempted": True,
                **(
                    _bounded_record(evidence)
                    if isinstance(evidence, dict)
                    else {}
                ),
            },
        )

    def _complete_salesforce_operation(
        self,
        key: str,
        operation: str,
        target: str,
        plan_hash: str,
        evidence: dict[str, Any],
    ) -> None:
        self._journal_salesforce_operation(
            "accepted",
            _required_idempotency_key(key),
            _bounded(operation, "operation", 100),
            _bounded(target, "target", 200),
            _required_preview_hash(plan_hash),
            _bounded_record(evidence),
        )

    def _prior_salesforce_operation(self, key: str) -> dict[str, Any] | None:
        journal = self.settings.journal_path
        if not journal.is_file():
            return None
        with journal.open("r", encoding="utf-8") as handle:
            recent = deque(handle, maxlen=5000)
        for line in reversed(recent):
            try:
                row = json.loads(line)
            except (TypeError, ValueError):
                continue
            if row.get("idempotencyKey") == key:
                return row
        return None

    def _journal_salesforce_operation(
        self,
        status: str,
        key: str,
        operation: str,
        target: str,
        plan_hash: str,
        evidence: dict[str, Any],
    ) -> None:
        journal = self.settings.journal_path
        journal.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        record = {
            "time": int(time.time()),
            "status": status,
            "idempotencyKey": key,
            "operation": operation,
            "target": target,
            "planHash": plan_hash,
            "evidence": evidence,
        }
        descriptor = os.open(journal, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":"), default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _query(self, soql: str) -> dict[str, Any]:
        result = self._request("GET", "/query", params={"q": soql})
        if not isinstance(result, dict):
            raise SalesforceUnavailableError("Salesforce query returned an invalid response")
        return result

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None, json: Any = None) -> Any:
        token, instance = self._authenticate()
        response = self.session.request(
            method,
            f"{instance}/services/data/v{self.settings.api_version}{path}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            params=params,
            json=json,
            timeout=30,
        )
        if response.status_code == 204:
            return {}
        if response.status_code not in {200, 201}:
            message = (
                f"Salesforce operation failed with status {response.status_code} "
                f"({_salesforce_error_summary(response)})"
            )
            if (
                400 <= response.status_code < 500
                and response.status_code not in {408, 409, 425, 429}
            ):
                raise SalesforceDefinitiveRejectionError(
                    response.status_code,
                    message,
                )
            raise SalesforceUnavailableError(message)
        return response.json()

    def _request_bytes(self, path: str) -> bytes:
        token, instance = self._authenticate()
        response = self.session.get(
            f"{instance}/services/data/v{self.settings.api_version}{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if response.status_code != 200:
            raise SalesforceUnavailableError(
                f"Salesforce attachment readback failed with status {response.status_code}"
            )
        return bytes(response.content)

    def _authenticate(self) -> tuple[str, str]:
        if self._token and self._instance_url and (self.settings.access_token or self._expires_at > time.time()):
            return self._token, self._instance_url
        if not self.settings.client_id or not self.settings.client_secret:
            raise SalesforceUnavailableError("Salesforce scoped credentials are not configured")
        if self.settings.username and self.settings.password:
            data = {
                "grant_type": "password",
                "client_id": self.settings.client_id,
                "client_secret": self.settings.client_secret,
                "username": self.settings.username,
                "password": self.settings.password,
            }
        elif self.settings.use_client_credentials:
            data = {
                "grant_type": "client_credentials",
                "client_id": self.settings.client_id,
                "client_secret": self.settings.client_secret,
            }
        else:
            raise SalesforceUnavailableError("Salesforce scoped credential grant is not configured")
        response = self.session.post(f"{self.settings.login_url}/services/oauth2/token", data=data, timeout=30)
        if response.status_code != 200:
            raise SalesforceUnavailableError("Salesforce scoped authentication failed")
        payload = response.json()
        self._token = str(payload.get("access_token") or "")
        self._instance_url = str(payload.get("instance_url") or self.settings.instance_url).rstrip("/")
        self._expires_at = time.time() + max(60, int(payload.get("expires_in") or 3600) - 120)
        if not self._token or not self._instance_url:
            raise SalesforceUnavailableError("Salesforce authentication response was incomplete")
        return self._token, self._instance_url


def _ticket_chatter_body(value: str) -> str:
    """Keep ticket Chatter concise, operational, and free of repeated intake narrative."""

    clean = _bounded(value, "chatter_body", 5_000)
    clean = re.sub(
        r"(?im)^\s*(?:\[\s*)?\d{4}-\d{2}-\d{2}"
        r"(?:[T\s]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|\s*UTC)?)?"
        r"(?:\s*\])?\s*(?:[-:\u2013\u2014]\s*)?",
        "",
        clean,
    ).strip()
    if not clean:
        raise SalesforceScopeError("Ticket note must contain a customer-safe outcome")
    if len(clean) > 2_000 or clean.count("\n") > 4:
        raise SalesforceScopeError(
            "Ticket Chatter must be one concise, net-new business update"
        )

    # A refunded invoice link is the only useful provider reference approved
    # for routine Chatter. Remove it from inspection, then restore it unchanged.
    allowed_links: list[str] = []

    def preserve_refund_invoice_link(match: re.Match[str]) -> str:
        url = match.group(0)
        lowered = url.casefold()
        if (
            "refund" in clean.casefold()
            and "invoice" in lowered
            and ("chargify" in lowered or "maxio" in lowered)
        ):
            token = f"__APPROVED_REFUND_INVOICE_LINK_{len(allowed_links)}__"
            allowed_links.append(url)
            return token
        return url

    inspected = re.sub(r"https?://[^\s<>()]+", preserve_refund_invoice_link, clean)
    forbidden = (
        r"\b(?:EmailMessage|providerResult|idempotency(?:\s+key)?|Command\s+Center|"
        r"Needs\s+Review|readback|connector|broker|runtime|stack\s+trace|"
        r"permission(?:s)?|access\s+diagnostic|validation(?:\s+rule)?|"
        r"required\s+closure\s+fields?|job\s+(?:id|cc-)|record\s+id)\b",
        r"\b(?:Salesforce|Maxio|Chargify)\b",
        r"\b(?:00X|02s|0D5|a0G|a0O|001|003)[A-Za-z0-9]{12,15}\b",
        r"\bcc-\d{8}T\d{6}Z-[A-Za-z0-9]+\b",
        r"\b(?:could\s+not|unable\s+to|failed\s+to)\s+(?:close|update|send|post|attach)\b",
        r"\bplease\s+(?:complete|fill|set)\b.{0,100}\b(?:field|ticket|close)\b",
    )
    if any(re.search(pattern, inspected, flags=re.IGNORECASE) for pattern in forbidden):
        raise SalesforceScopeError(
            "Ticket note contains internal system, provider, validation, or recovery details. "
            "Rewrite it as the plain customer outcome or useful business follow-up."
        )
    recap_or_narrative = (
        r"(?im)^\s*(?:Cause:\s*)?(?:the\s+)?customer\b.{0,220}\b(?:needed|wanted|requested|asked)\b",
        r"\b(?:internal\s+)?(?:request|ticket)\s+(?:was|has\s+been)\s+(?:created|opened|submitted)\b",
        r"\b(?:the\s+)?(?:agent|technician|representative)\s+(?:confirmed|explained|advised|told)\b",
        r"\b(?:positive|neutral)\s+sentiment\b",
        r"\b(?:customer|they)\s+(?:was|were|felt|seemed)\s+"
        r"(?:happy|pleased|satisfied|delighted|relieved|comfortable|better|good)\b",
        r"\b(?:customer|they)\s+(?:thanked|appreciated)\b",
    )
    if any(re.search(pattern, inspected, flags=re.IGNORECASE) for pattern in recap_or_narrative):
        raise SalesforceScopeError(
            "Ticket Chatter must not repeat the ticket request, contact or process narrative, "
            "or routine sentiment. Supply only net-new resolution progress, a completed action, "
            "a useful diagnostic insight, or a real business follow-up."
        )
    upset_language = re.search(
        r"\b(?:negative\s+sentiment|customer\s+(?:was|felt|seemed)\s+"
        r"(?:upset|angry|frustrated|irate|dissatisfied)|customer\s+escalat(?:ed|ion))\b",
        inspected,
        flags=re.IGNORECASE,
    )
    if upset_language:
        handling = re.search(
            r"(?im)^\s*Priority/handling:\s*(.+)$",
            inspected,
        )
        material_change = re.search(
            r"\b(?:priority\s+(?:was\s+)?(?:raised|increased|changed)|urgent|"
            r"escalat(?:ed|ion)|immediate|manager|supervisor|retention|safety|"
            r"chargeback|legal|formal\s+complaint)\b",
            handling.group(1) if handling else "",
            flags=re.IGNORECASE,
        )
        if not material_change:
            raise SalesforceScopeError(
                "Customer sentiment belongs in Chatter only when it materially changes priority or handling"
            )
    for index, url in enumerate(allowed_links):
        inspected = inspected.replace(f"__APPROVED_REFUND_INVOICE_LINK_{index}__", url)
    return inspected.strip()


def ticket_chatter_update_body(
    cause: str = "",
    resolution: str = "",
    next_steps: str = "",
    priority_context: str = "",
    *,
    update: str = "",
) -> str:
    """Build one non-redundant Chatter update without manufacturing filler sections."""

    def section(value: str, label: str, limit: int = 700) -> str:
        clean = " ".join(str(value or "").split())
        if len(clean) > limit:
            raise SalesforceScopeError(f"{label} must be at most {limit} characters")
        return clean

    clean_update = section(update, "update")
    sections = [
        ("Cause", section(cause, "cause")),
        ("Resolution", section(resolution, "resolution")),
        ("Next steps", section(next_steps, "next_steps")),
    ]
    sections = [(label, value) for label, value in sections if value]
    if clean_update and sections:
        raise SalesforceScopeError(
            "Plain update cannot be combined with structured sections; use only the genuinely needed form"
        )

    filler_only = {
        "n/a",
        "none",
        "not applicable",
        "not yet confirmed",
        "not yet resolved",
        "no further action is required",
        "pending",
    }
    for label, value in sections:
        if value.rstrip(".").casefold() in filler_only:
            raise SalesforceScopeError(
                f"{label.lower()} contains no new information; omit it instead of adding filler"
            )

    if clean_update:
        lines = [clean_update]
    elif len(sections) == 1:
        lines = [sections[0][1]]
    else:
        lines = [f"{label}: {value}" for label, value in sections]

    clean_priority = " ".join(str(priority_context or "").split())
    if clean_priority:
        if len(clean_priority) > 500:
            raise SalesforceScopeError("priority_context must be at most 500 characters")
        lines.append(f"Priority/handling: {clean_priority}")
    if not lines:
        raise SalesforceScopeError(
            "Ticket update must add a net-new resolution detail, completed action, insight, or follow-up"
        )
    return _ticket_chatter_body("\n".join(lines))


def _ticket_internal_request_body(value: str, recipient: dict[str, Any]) -> str:
    """Keep an employee request short while the broker owns the greeting and mention."""

    clean = str(value or "").strip()
    names = {
        " ".join(str(recipient.get("Name") or "").split()),
        " ".join(str(recipient.get("FirstName") or "").split()),
    }
    for name in sorted((item for item in names if item), key=len, reverse=True):
        clean = re.sub(
            rf"(?is)^\s*(?:hey|hi)\s+@?{re.escape(name)}\s*[,!:.-]\s*",
            "",
            clean,
            count=1,
        )
    clean = _ticket_chatter_body(clean)
    if len(clean) > 600 or clean.count("\n") > 1:
        raise SalesforceScopeError(
            "Internal requests must be one short conversational message of at most 600 characters"
        )
    return clean


def _is_nova_internal_email(value: str) -> bool:
    address = str(value or "").strip().casefold()
    if not EMAIL.fullmatch(address):
        return False
    configured = str(
        os.getenv("SALESFORCE_INTERNAL_USER_EMAIL_DOMAINS")
        or "novapointofsale.com"
    )
    allowed = {
        domain.strip().casefold().lstrip("@")
        for domain in configured.split(",")
        if domain.strip()
    }
    return address.rsplit("@", 1)[-1] in allowed


def _escape_soql(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _escape_sosl(value: str) -> str:
    """Escape every Salesforce SOSL reserved character inside one FIND phrase."""

    return re.sub(
        r"""([?&|!{}\[\]()^~*:\\"'+-])""",
        lambda match: f"\\{match.group(1)}",
        value,
    )


def _support_email_account_is_eligible(
    account: dict[str, Any],
    *,
    expected_account_id: str,
) -> bool:
    account_id = str(account.get("Id") or "").strip()
    name = str(account.get("Name") or "").strip()
    return bool(
        account_id == expected_account_id
        and name
        and account.get("Fake_Account__c") is False
        and not any(
            marker in name.casefold()
            for marker in SUPPORT_EMAIL_EXCLUDED_ACCOUNT_PARTS
        )
    )


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _account_360_account_is_exact(
    record: dict[str, Any],
    search: str,
    *,
    is_record_id: bool,
) -> bool:
    if is_record_id:
        return str(record.get("Id") or "") == search
    target = _normalized_text(search)
    return any(
        _normalized_text(record.get(field)) == target
        for field in ("Name", "Company_Username__c", "Nova_ID__c", "Phone", "Phone_II__c")
        if record.get(field)
    )


def _account_360_candidate(record: dict[str, Any], sources: set[str]) -> dict[str, Any]:
    return {
        "accountId": str(record.get("Id") or ""),
        "accountName": str(record.get("Name") or "")[:255],
        "companyUsername": str(record.get("Company_Username__c") or "")[:255],
        "phone": str(record.get("Phone") or "")[:80],
        "matchSources": sorted(sources) if sources else ["account_name"],
    }


def _normalized_picklist_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _normalized_csv(value: Any) -> str:
    parts = [part.strip() for part in str(value or "").split(",") if part.strip()]
    numeric = sorted({str(int(part)) for part in parts if part.isdigit()}, key=int)
    return ",".join(numeric)


def _exact_location_csv(value: Any) -> str:
    parts = [part.strip() for part in str(value or "").split(",") if part.strip()]
    if not parts:
        return ""
    normalized = [_normalized_location_id(part) for part in parts]
    if any(not part for part in normalized) or len(set(normalized)) != len(normalized):
        return ""
    return ",".join(sorted(normalized, key=int))


def _unique_nova_location_ids(
    value: Any,
    label: str,
    *,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list) or len(value) > 100 or (not value and not allow_empty):
        qualifier = "0-100" if allow_empty else "1-100"
        raise SalesforceScopeError(
            f"{label} must contain {qualifier} exact positive Nova location IDs"
        )
    normalized = [_normalized_location_id(raw) for raw in value]
    if any(not item for item in normalized):
        raise SalesforceScopeError(
            f"{label} must contain exact positive integer Nova location IDs"
        )
    if len(set(normalized)) != len(normalized):
        raise SalesforceScopeError(f"{label} cannot contain duplicates")
    return sorted(normalized, key=int)


def _is_storage_location(location: Mapping[str, Any]) -> bool:
    return bool(
        _normalized_text(str(location.get("Status__c") or "")) == "storage"
        or re.search(
            r"\bstorages?\b",
            str(location.get("Name") or ""),
            re.IGNORECASE,
        )
    )


def _ticket_cancellation_order_coverage(
    records: Any,
    ticket_number: str,
) -> dict[str, Any]:
    if not isinstance(records, list):
        raise SalesforceUnavailableError(
            "Salesforce cancellation-order coverage returned an unexpected shape"
        )
    clean_ticket_number = str(ticket_number or "").strip()
    if not clean_ticket_number:
        raise SalesforceScopeError(
            "Account closure requires an exact cancellation ticket number"
        )
    ticket_marker = re.compile(
        rf"\bticket\s+{re.escape(clean_ticket_number)}\b",
        re.IGNORECASE,
    )
    evidence_marker = re.compile(
        r"\bMaxio location-component evidence:\s*[a-f0-9]{64}\b",
        re.IGNORECASE,
    )
    matched: list[dict[str, Any]] = []
    seen_subscriptions: set[int] = set()
    seen_locations: set[str] = set()
    for raw in records:
        if not isinstance(raw, Mapping):
            continue
        record = dict(raw)
        description = str(record.get("Description__c") or "")
        count = _integer_identifier(
            record.get("Total_Number_of_Locations_for_this_order__c")
        )
        if (
            count is None
            or count >= 0
            or not ticket_marker.search(description)
            or not evidence_marker.search(description)
        ):
            continue
        subscription_id = _numeric_identifier(
            record.get("Chargify_Subscription_ID__c")
        )
        location_csv = _exact_location_csv(record.get("Location_I_D__c"))
        location_ids = location_csv.split(",") if location_csv else []
        expected_contract = (
            f"-{len(location_ids)} Location"
            f"{'s' if len(location_ids) != 1 else ''}. Billing Automation Order"
        )
        if (
            subscription_id is None
            or not location_ids
            or count != -len(location_ids)
            or str(record.get("Contract_Name__c") or "") != expected_contract
            or subscription_id in seen_subscriptions
            or seen_locations.intersection(location_ids)
        ):
            raise SalesforceScopeError(
                "Account closure found a ticket-linked cancellation order whose "
                "location-only quantity, Contract Name, location IDs, or subscription "
                "grouping was not exact"
            )
        seen_subscriptions.add(subscription_id)
        seen_locations.update(location_ids)
        matched.append(
            {
                "orderId": _required_id(
                    str(record.get("Id") or ""),
                    "ticket-linked cancellation order id",
                ),
                "subscriptionId": subscription_id,
                "locationIds": location_ids,
                "locationQuantity": len(location_ids),
            }
        )
    if not matched:
        raise SalesforceScopeError(
            "Account closure requires exact ticket-linked cancellation orders with "
            "Maxio location-component evidence"
        )
    return {
        "orderIds": sorted(str(row["orderId"]) for row in matched),
        "subscriptionIds": sorted(
            int(row["subscriptionId"]) for row in matched
        ),
        "locationIds": sorted(seen_locations, key=int),
        "locationOrderQuantityTotal": sum(
            int(row["locationQuantity"]) for row in matched
        ),
        "orderCount": len(matched),
    }


def _maxio_account_reconciliation_evidence(value: Any) -> dict[str, Any]:
    expected_keys = {
        "subscription_ids",
        "open_subscription_ids",
        "open_location_component_count",
        "maxio_snapshot_hash",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise SalesforceScopeError(
            "maxio_reconciliation_evidence must contain only "
            "subscription_ids, open_subscription_ids, "
            "open_location_component_count, and maxio_snapshot_hash"
        )
    raw_subscription_ids = value["subscription_ids"]
    if (
        not isinstance(raw_subscription_ids, list)
        or not raw_subscription_ids
        or len(raw_subscription_ids) > 100
    ):
        raise SalesforceScopeError(
            "Maxio subscription_ids must contain 1-100 exact subscription IDs"
        )
    subscription_ids: list[int] = []
    seen_subscriptions: set[int] = set()
    for raw in raw_subscription_ids:
        subscription_id = _numeric_identifier(raw)
        if subscription_id is None:
            raise SalesforceScopeError(
                "Maxio subscription_ids must contain positive integers"
            )
        if subscription_id in seen_subscriptions:
            raise SalesforceScopeError(
                "Maxio subscription_ids cannot contain duplicates"
            )
        seen_subscriptions.add(subscription_id)
        subscription_ids.append(subscription_id)

    raw_open_ids = value["open_subscription_ids"]
    if not isinstance(raw_open_ids, list) or len(raw_open_ids) > 100:
        raise SalesforceScopeError(
            "Maxio open_subscription_ids must contain 0-100 exact subscription IDs"
        )
    open_subscription_ids: list[int] = []
    seen: set[int] = set()
    for raw in raw_open_ids:
        subscription_id = _numeric_identifier(raw)
        if subscription_id is None:
            raise SalesforceScopeError(
                "Maxio open_subscription_ids must contain positive integers"
            )
        if subscription_id in seen:
            raise SalesforceScopeError(
                "Maxio open_subscription_ids cannot contain duplicates"
            )
        seen.add(subscription_id)
        open_subscription_ids.append(subscription_id)
    if not set(open_subscription_ids).issubset(set(subscription_ids)):
        raise SalesforceScopeError(
            "Maxio open_subscription_ids must be a subset of subscription_ids"
        )
    count = _integer_identifier(value["open_location_component_count"])
    if count is None or count < 0 or count > 100000:
        raise SalesforceScopeError(
            "Maxio open_location_component_count must be an integer from 0 to 100000"
        )
    return {
        "subscriptionIds": sorted(subscription_ids),
        "openSubscriptionIds": sorted(open_subscription_ids),
        "openLocationComponentCount": count,
        "maxioSnapshotHash": _required_preview_hash(
            value["maxio_snapshot_hash"]
        ),
    }


def _normalized_location_id(value: Any) -> str:
    if isinstance(value, bool):
        return ""
    clean = str(value or "").strip()
    if not clean:
        return ""
    try:
        parsed = Decimal(clean)
    except InvalidOperation:
        return ""
    if not parsed.is_finite() or parsed != parsed.to_integral_value() or parsed < 1:
        return ""
    return str(int(parsed))


def _stable_plan_hash(plan: dict[str, Any]) -> str:
    rendered = json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


_PAYMENT_CARD_NUMBER_CANDIDATE = re.compile(
    r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"
)
_LABELED_PAYMENT_SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(card(?:\s+number|\s*#)?|credit\s+card)\s*[:#=-]?\s*[^\n|;]{3,80}"
    ),
    re.compile(
        r"(?i)\b(cvv|cvc|security\s+code)\s*[:#=-]?\s*[^\s,|;]{2,20}"
    ),
    re.compile(
        r"(?i)\b(exp(?:iration|iry)?(?:\s+date)?)\s*[:#=-]?\s*[^\s,|;]{2,20}"
    ),
    re.compile(
        r"(?i)\b(name\s+on\s+card)\s*[:#=-]?\s*[^\n|;]{2,80}"
    ),
    re.compile(
        r"(?i)\b(billing\s+address|billing\s+(?:zip|postal\s+code))\s*[:#=-]?\s*[^\n|;]{2,120}"
    ),
)


def _redact_ticket_payment_card_text(value: str) -> str:
    """Remove raw card data from bounded ticket text without returning the original."""

    text = str(value or "")
    if not text:
        return text

    def redact_pan(match: re.Match[str]) -> str:
        candidate = match.group(0)
        digits = re.sub(r"\D", "", candidate)
        return "[redacted]" if _is_luhn_payment_card_number(digits) else candidate

    redacted = _PAYMENT_CARD_NUMBER_CANDIDATE.sub(redact_pan, text)
    for pattern in _LABELED_PAYMENT_SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: f"{match.group(1)}: [redacted]", redacted)
    return redacted


def _is_luhn_payment_card_number(value: str) -> bool:
    if not re.fullmatch(r"\d{13,19}", value):
        return False
    total = 0
    parity = len(value) % 2
    for index, character in enumerate(value):
        digit = int(character)
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _required_preview_hash(value: Any) -> str:
    clean = str(value or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{64}", clean):
        raise SalesforceScopeError("preview_hash must be the exact 64-character plan hash")
    return clean


def _maxio_location_deallocation_evidence(
    value: Any,
) -> dict[int, dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > 100:
        raise SalesforceScopeError(
            "maxio_deallocation_evidence must contain 1-100 exact subscription entries"
        )
    expected_keys = {
        "subscription_id",
        "location_component_deallocation_count",
        "maxio_preview_hash",
    }
    evidence: dict[int, dict[str, Any]] = {}
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != expected_keys:
            raise SalesforceScopeError(
                "each Maxio deallocation entry must contain only subscription_id, "
                "location_component_deallocation_count, and maxio_preview_hash"
            )
        subscription_id = _numeric_identifier(raw["subscription_id"])
        if subscription_id is None:
            raise SalesforceScopeError(
                "Maxio deallocation subscription_id must be a positive integer"
            )
        count = _numeric_identifier(
            raw["location_component_deallocation_count"]
        )
        if count is None or count > 100:
            raise SalesforceScopeError(
                "Maxio location_component_deallocation_count must be between 1 and 100"
            )
        preview_hash = _required_preview_hash(raw["maxio_preview_hash"])
        if subscription_id in evidence:
            raise SalesforceScopeError(
                "maxio_deallocation_evidence cannot contain duplicate subscriptions"
            )
        evidence[subscription_id] = {
            "subscriptionId": subscription_id,
            "locationComponentDeallocationCount": count,
            "maxioPreviewHash": preview_hash,
        }
    return evidence


def _numeric_identifier(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    clean = str(value).strip()
    if not clean:
        return None
    try:
        decimal_value = Decimal(clean)
    except (InvalidOperation, ValueError):
        return None
    if decimal_value != decimal_value.to_integral_value() or decimal_value <= 0:
        return None
    return int(decimal_value)


def _integer_identifier(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    clean = str(value).strip()
    if not clean:
        return None
    try:
        decimal_value = Decimal(clean)
    except (InvalidOperation, ValueError):
        return None
    if not decimal_value.is_finite() or decimal_value != decimal_value.to_integral_value():
        return None
    return int(decimal_value)


def _positive_salesforce_external_id(value: Any, label: str) -> int:
    clean = _numeric_identifier(value)
    if clean is None:
        raise SalesforceScopeError(f"{label} must be a positive integer")
    return clean


def _nonnegative_cents(value: Any, label: str) -> int:
    try:
        clean = int(value)
    except (TypeError, ValueError) as exc:
        raise SalesforceScopeError(f"{label} must be an integer") from exc
    if isinstance(value, bool) or clean < 0 or clean > 100_000_000:
        raise SalesforceScopeError(f"{label} must be between 0 and 100000000")
    return clean


def _unique_positive_ids(value: Any, label: str, *, limit: int) -> list[int]:
    if not isinstance(value, list) or len(value) > limit:
        raise SalesforceScopeError(f"{label} must be a list with at most {limit} values")
    clean: list[int] = []
    seen: set[int] = set()
    for raw in value:
        item = _positive_salesforce_external_id(raw, label)
        if item in seen:
            raise SalesforceScopeError(f"{label} cannot contain duplicate values")
        seen.add(item)
        clean.append(item)
    return sorted(clean)


def _unique_salesforce_record_ids(
    value: Any,
    label: str,
    *,
    limit: int,
) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > limit:
        raise SalesforceScopeError(f"{label} must be a list with at most {limit} values")
    clean: list[str] = []
    seen: set[str] = set()
    for raw in value:
        item = _required_id(raw, label)
        if item in seen:
            raise SalesforceScopeError(f"{label} cannot contain duplicate values")
        seen.add(item)
        clean.append(item)
    return sorted(clean)


def _salesforce_date(value: Any, label: str) -> str:
    clean = str(value or "").strip()
    try:
        parsed = datetime.strptime(clean, "%Y-%m-%d")
    except ValueError as exc:
        raise SalesforceScopeError(f"{label} must use YYYY-MM-DD") from exc
    return parsed.strftime("%Y-%m-%d")


def _salesforce_datetime(value: Any, label: str) -> datetime:
    clean = str(value or "").strip()
    if not clean:
        raise SalesforceScopeError(f"{label} is required")
    try:
        parsed = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SalesforceScopeError(f"{label} was not a valid Salesforce timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _within_first_three_calendar_months(created_at: datetime, action_at: datetime) -> bool:
    created = created_at.astimezone(timezone.utc)
    action = action_at.astimezone(timezone.utc)
    return created <= action < _three_calendar_month_boundary(created)


def _three_calendar_month_boundary(created_at: datetime) -> datetime:
    created = created_at.astimezone(timezone.utc)
    month_index = (created.month - 1) + 3
    boundary_year = created.year + month_index // 12
    boundary_month = month_index % 12 + 1
    boundary_day = min(created.day, monthrange(boundary_year, boundary_month)[1])
    return created.replace(
        year=boundary_year,
        month=boundary_month,
        day=boundary_day,
    )


def _merchant_provider(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())
    aliases = {
        "worldpay": "Worldpay",
        "creditcall": "Creditcall",
        "authorizenet": "Authorize.net",
        "propelr": "Propelr",
    }
    provider = aliases.get(normalized)
    if provider is None:
        raise SalesforceScopeError(
            "merchant_provider is required for every new location and must be one of: "
            + ", ".join(NOVA_INTEGRATED_MERCHANT_PROVIDERS)
        )
    return provider


def _salesforce_field_matches(before: Any, desired: Any, field: str) -> bool:
    if field in {
        "Bill_Amount__c",
        "Flat_Rate_Amount__c",
        "Monthly_Revenue__c",
    }:
        return _decimal_currency_field_to_cents(before) == _decimal_currency_field_to_cents(desired)
    if field in {
        "Billing_Circle_Client_ID__c",
        "Billing_Circle_Schedule_ID__c",
        "Chargify_Subscription_ID__c",
    }:
        return _numeric_identifier(before) == _numeric_identifier(desired)
    if desired is None:
        return before is None or not str(before).strip()
    if isinstance(desired, bool):
        if isinstance(before, bool):
            return before is desired
        return str(before).strip().casefold() == str(desired).casefold()
    return str(before or "").strip().casefold() == str(desired).strip().casefold()


def _required_idempotency_key(value: Any) -> str:
    clean = str(value or "").strip()
    if not IDEMPOTENCY_KEY.fullmatch(clean):
        raise SalesforceScopeError("idempotency_key must contain 8-240 safe characters")
    return clean


def _validated_cancellation_pdf_identity(file_name: Any, sha256: Any) -> tuple[str, str]:
    clean_name = str(file_name or "").strip()
    if (
        not clean_name
        or len(clean_name) > 180
        or clean_name != Path(clean_name).name
        or not clean_name.casefold().endswith(".pdf")
    ):
        raise SalesforceScopeError("file_name must be one bounded PDF base name")
    clean_digest = str(sha256 or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{64}", clean_digest):
        raise SalesforceScopeError("sha256 must be the exact lowercase PDF digest")
    return clean_name, clean_digest


def _validated_cancellation_email_identity(file_name: Any, sha256: Any) -> tuple[str, str]:
    clean_name, clean_digest = _validated_ticket_attachment_identity(
        file_name,
        sha256,
    )
    if Path(clean_name).suffix.casefold() != ".eml":
        raise SalesforceScopeError("file_name must be one bounded EML base name")
    return clean_name, clean_digest


def _validated_ticket_attachment_identity(file_name: Any, sha256: Any) -> tuple[str, str]:
    clean_name = str(file_name or "").strip()
    suffix = Path(clean_name).suffix.casefold()
    if (
        not clean_name
        or len(clean_name) > 180
        or clean_name != Path(clean_name).name
        or suffix not in TICKET_ATTACHMENT_EXTENSIONS
    ):
        raise SalesforceScopeError(
            "file_name must be one bounded PDF, image, text, email, or Office-document base name"
        )
    clean_digest = str(sha256 or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{64}", clean_digest):
        raise SalesforceScopeError("sha256 must be the exact lowercase attachment digest")
    return clean_name, clean_digest


def _validate_ticket_attachment_content(file_name: str, content: bytes) -> None:
    suffix = Path(file_name).suffix.casefold()
    if suffix == ".pdf" and not content.startswith(b"%PDF-"):
        raise SalesforceScopeError("ticket attachment signature is not PDF")
    if suffix in TICKET_ATTACHMENT_ARCHIVE_EXTENSIONS and not content.startswith(b"PK"):
        raise SalesforceScopeError("ticket Office attachment signature is invalid")
    signatures = TICKET_ATTACHMENT_IMAGE_SIGNATURES.get(suffix)
    if signatures and not content.startswith(signatures):
        raise SalesforceScopeError("ticket image attachment signature is invalid")
    if suffix == ".webp" and not (
        len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    ):
        raise SalesforceScopeError("ticket image attachment signature is invalid")
    if suffix in {".csv", ".eml", ".json", ".md", ".tsv", ".txt"} and b"\x00" in content[:4096]:
        raise SalesforceScopeError("ticket text attachment contains binary content")


def _required_positive_cents(value: Any, name: str) -> int:
    try:
        clean = int(value)
    except (TypeError, ValueError) as exc:
        raise SalesforceScopeError(f"{name} must be an integer") from exc
    if isinstance(value, bool) or clean <= 0 or clean > 10_000_000:
        raise SalesforceScopeError(f"{name} must be between 1 and 10000000")
    return clean


def _approval_provider_success(value: Any) -> bool:
    records = value if isinstance(value, list) else []
    if isinstance(value, dict):
        for key in ("results", "requests"):
            if isinstance(value.get(key), list):
                records = value[key]
                break
        else:
            records = [value]
    return any(
        isinstance(record, dict)
        and (
            record.get("success") is True
            or _normalized_text(str(record.get("status") or "")) in {"submitted", "pending", "approved"}
        )
        for record in records
    )


def _currency_from_cents(value: int) -> str:
    dollars, cents = divmod(value, 100)
    return f"${dollars:,}.{cents:02d}"


def _decimal_currency_field_to_cents(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
    cents = amount * 100
    return int(cents) if cents == cents.to_integral_value() else None


def _verify_refund_template_preview(
    preview: dict[str, str],
    *,
    expected_amount: str,
    brand_template_id: str,
) -> dict[str, Any]:
    return _verify_amount_template_preview(
        preview,
        expected_amount=expected_amount,
        brand_template_id=brand_template_id,
        expected_subject=REFUND_SUBMITTED_TEMPLATE_SUBJECT,
        amount_result_key="refundAmount",
    )


def _verify_credit_template_preview(
    preview: dict[str, str],
    *,
    expected_amount: str,
    brand_template_id: str,
) -> dict[str, Any]:
    return _verify_amount_template_preview(
        preview,
        expected_amount=expected_amount,
        brand_template_id=brand_template_id,
        expected_subject=CREDIT_APPLIED_TEMPLATE_SUBJECT,
        amount_result_key="creditAmount",
    )


def _validate_billing_inquiry_insert(
    message: str,
    *,
    account_name: str,
    last4: str,
) -> None:
    normalized = _normalized_text(message)
    forbidden_fragments = (
        _normalized_text(account_name),
        _normalized_text(last4),
        "hello ",
        "hi ",
        "dear ",
        "thank you",
        "sincerely",
        "regards",
        "nova support",
        "billing@",
        "support@",
        "(888)",
        "novapos billing inquiry update",
        "card ending",
        "last 4",
    )
    if any(fragment and fragment in normalized for fragment in forbidden_fragments):
        raise SalesforceScopeError(
            "message must contain only the billing update; the approved template supplies "
            "the account, card, greeting, subject, contact details, and signature"
        )
    if EMAIL_IN_TEXT.search(message) or re.search(r"https?://|www\.", message, re.IGNORECASE):
        raise SalesforceScopeError(
            "message must not inject email addresses, links, or template boilerplate"
        )
    if (
        "<" in message
        or ">" in message
        or any(marker in message for marker in ("{!", "{{", "}}", "]]>"))
        or re.search(r"\[[^\]\r\n]{2,}\]", message)
    ):
        raise SalesforceScopeError(
            "message must be bounded plain text without HTML or unresolved template tokens"
        )


def _insert_billing_inquiry_details(
    preview: dict[str, str],
    *,
    account_name: str,
    last4: str,
    message: str,
) -> dict[str, str]:
    replacements = (
        (BILLING_INQUIRY_ACCOUNT_PLACEHOLDER, account_name),
        (BILLING_INQUIRY_LAST4_PLACEHOLDER, last4),
        (BILLING_INQUIRY_MESSAGE_PLACEHOLDER, message),
    )
    rendered = dict(preview)
    for body_key in ("htmlBody", "plainTextBody"):
        body = str(rendered.get(body_key) or "")
        for placeholder, value in replacements:
            if body.count(placeholder) != 1:
                raise SalesforceUnavailableError(
                    "Approved billing inquiry template placeholders did not match policy"
                )
            inserted_value = escape_xml(value) if body_key == "htmlBody" else value
            body = body.replace(placeholder, inserted_value, 1)
        rendered[body_key] = body
    escaped_message = escape_xml(message)
    if (
        str(rendered.get("htmlBody") or "").count(escaped_message) != 1
        or str(rendered.get("plainTextBody") or "").count(message) != 1
    ):
        raise SalesforceUnavailableError(
            "Approved billing inquiry template did not contain the editable message exactly once"
        )
    return rendered


def _bounded_support_one_off_message(value: Any) -> str:
    message = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [
        re.sub(r"[ \t]+", " ", paragraph).strip()
        for paragraph in re.split(r"\n[ \t]*\n", message)
        if paragraph.strip()
    ]
    if not paragraphs or len(paragraphs) > 3:
        raise SalesforceScopeError(
            "message must contain one to three short customer-relevant paragraphs"
        )
    message = _bounded("\n\n".join(paragraphs), "message", 1600)
    normalized = _normalized_text(message)
    forbidden_fragments = (
        "hello ",
        "hi ",
        "dear ",
        "thank you",
        "sincerely",
        "regards",
        "nova pos team",
        "nova point of sale support",
        "nova support team",
        "izhak musli",
        "itzhak musli",
        "support@",
        "billing@",
        "subject:",
    )
    if any(fragment in normalized for fragment in forbidden_fragments):
        raise SalesforceScopeError(
            "message must contain only the customer-relevant update; the approved template "
            "supplies the greeting, subject, sender, and team signature"
        )
    if EMAIL_IN_TEXT.search(message):
        raise SalesforceScopeError("message must not inject email addresses")
    if (
        "<" in message
        or ">" in message
        or any(
            marker in message for marker in ("{!", "{{", "}}", "]]>")
        )
        or re.search(r"\[[^\]\r\n]{2,}\]", message)
    ):
        raise SalesforceScopeError(
            "message must be bounded plain text without HTML or unresolved template tokens"
        )
    for match in re.finditer(r"(?i)\b(?:https?://|www\.)[^\s<>()]+", message):
        raw_url = match.group(0).rstrip(".,;:!?")
        parsed = urlsplit(raw_url)
        hostname = (parsed.hostname or "").casefold()
        if (
            parsed.scheme.casefold() != "https"
            or not hostname
            or not (
                hostname == "novapointofsale.com"
                or hostname.endswith(".novapointofsale.com")
            )
        ):
            raise SalesforceScopeError(
                "message links must use HTTPS on novapointofsale.com"
            )
    return message


def _insert_support_one_off_message(
    preview: dict[str, str],
    *,
    message: str,
) -> dict[str, str]:
    rendered = dict(preview)
    for body_key in ("htmlBody", "plainTextBody"):
        body = str(rendered.get(body_key) or "")
        if body.count(SUPPORT_ONE_OFF_MESSAGE_PLACEHOLDER) != 1:
            raise SalesforceUnavailableError(
                "Approved support one-off template placeholder did not match policy"
            )
        inserted_value = (
            escape_xml(message).replace("\n", "<br/>")
            if body_key == "htmlBody"
            else message
        )
        rendered[body_key] = body.replace(
            SUPPORT_ONE_OFF_MESSAGE_PLACEHOLDER,
            inserted_value,
            1,
        )
    escaped_message = escape_xml(message).replace("\n", "<br/>")
    if (
        str(rendered.get("htmlBody") or "").count(escaped_message) != 1
        or str(rendered.get("plainTextBody") or "").count(message) != 1
    ):
        raise SalesforceUnavailableError(
            "Approved support one-off template did not contain the editable message exactly once"
        )
    return rendered


def _normalize_agent_email_signature(
    preview: dict[str, str],
    *,
    department: str,
) -> dict[str, str]:
    clean_department = str(department or "").strip().casefold()
    desired = "Nova POS Team" if clean_department == "billing" else "Nova Point of Sale Support"
    rendered = dict(preview)
    replacements = (
        r"\b(?:Izhak|Itzhak)\s+Musli\b",
        r"\bThe\s+NovaPOS\s+support\s+team\b",
        r"\bThe\s+Nova\s+Support\s+Team\b",
        r"\bNova\s+Support\s+Team\b",
    )
    for body_key in ("htmlBody", "plainTextBody"):
        body = str(rendered.get(body_key) or "")
        for pattern in replacements:
            body = re.sub(pattern, desired, body, flags=re.IGNORECASE)
        rendered[body_key] = body
    return rendered


def _verify_agent_email_signature(
    preview: dict[str, str],
    *,
    required_signature: str | None = None,
) -> None:
    html_body = str(preview.get("htmlBody") or "")
    plain_body = str(preview.get("plainTextBody") or "")
    for personal_name in (r"\bIzhak\s+Musli\b", r"\bItzhak\s+Musli\b"):
        if re.search(personal_name, html_body, re.IGNORECASE) or re.search(
            personal_name,
            plain_body,
            re.IGNORECASE,
        ):
            raise SalesforceUnavailableError(
                "Rendered agent email contains a personal-name signature"
            )
    if required_signature:
        if (
            _normalized_email_body(html_body).count(
                _normalized_text(required_signature)
            )
            != 1
            or _normalized_email_body(plain_body).count(
                _normalized_text(required_signature)
            )
            != 1
        ):
            raise SalesforceUnavailableError(
                "Rendered agent email did not contain the approved team signature exactly once"
            )


def _verify_approved_template_preview(
    preview: dict[str, str],
    *,
    expected_subject: str,
    brand_template_id: str,
    required_fragments: Collection[str],
) -> dict[str, Any]:
    subject = str(preview.get("subject") or "").strip()
    html_body = str(preview.get("htmlBody") or "")
    plain_body = str(preview.get("plainTextBody") or "")
    if subject != expected_subject:
        raise SalesforceUnavailableError(
            "Rendered approved email subject did not match policy"
        )
    if not html_body.strip() or not plain_body.strip():
        raise SalesforceUnavailableError(
            "Rendered approved email is missing HTML or plain-text content"
        )
    for marker in ("{!", "{{", "}}", "]]>"):
        if marker in html_body or marker in plain_body:
            raise SalesforceUnavailableError(
                "Rendered approved email contains unresolved template content"
            )
    if re.search(r"\[[^\]\r\n]{2,}\]", html_body) or re.search(
        r"\[[^\]\r\n]{2,}\]",
        plain_body,
    ):
        raise SalesforceUnavailableError(
            "Rendered approved email contains an unresolved manual placeholder"
        )
    if "styleInsert" not in html_body or "ImageServer" not in html_body:
        raise SalesforceUnavailableError(
            "Rendered approved email did not include the Salesforce letterhead"
        )
    _verify_agent_email_signature(preview)
    normalized_html = _normalized_email_body(html_body)
    normalized_plain = _normalized_email_body(plain_body)
    for fragment in required_fragments:
        normalized_fragment = _normalized_text(fragment)
        if normalized_fragment and (
            normalized_fragment not in normalized_html
            or normalized_fragment not in normalized_plain
        ):
            raise SalesforceUnavailableError(
                "Rendered approved email did not contain the verified inserted detail"
            )
    for phrase in (
        "hello ",
        "dear ",
        "the nova support team",
        "billing@novapointofsale.com",
    ):
        if normalized_plain.count(phrase) > 1:
            raise SalesforceUnavailableError(
                "Rendered approved email greeting, signature, or contact detail was duplicated"
            )
    return {
        "verified": True,
        "subject": subject,
        "brandTemplateId": brand_template_id,
        "htmlLength": len(html_body),
        "plainTextLength": len(plain_body),
        "htmlSha256": hashlib.sha256(html_body.encode("utf-8")).hexdigest(),
        "plainTextSha256": hashlib.sha256(plain_body.encode("utf-8")).hexdigest(),
        "letterheadIncluded": True,
        "mergeFieldsResolved": True,
        "manualPlaceholdersResolved": True,
        "duplicateTemplateDetails": False,
    }


def _verify_sensitive_template_preview(
    preview: dict[str, str],
    *,
    expected_subject: str,
) -> dict[str, Any]:
    """Verify a secret-bearing template without deriving public fingerprints."""

    subject = str(preview.get("subject") or "").strip()
    html_body = str(preview.get("htmlBody") or "")
    plain_body = str(preview.get("plainTextBody") or "")
    if subject != expected_subject:
        raise SalesforceUnavailableError(
            "Rendered sensitive email subject did not match policy"
        )
    if not html_body.strip() or not plain_body.strip():
        raise SalesforceUnavailableError(
            "Rendered sensitive email is missing HTML or plain-text content"
        )
    for marker in ("{!", "{{", "}}", "]]>"):
        if marker in html_body or marker in plain_body:
            raise SalesforceUnavailableError(
                "Rendered sensitive email contains unresolved template content"
            )
    if re.search(r"\[[^\]\r\n]{2,}\]", html_body) or re.search(
        r"\[[^\]\r\n]{2,}\]",
        plain_body,
    ):
        raise SalesforceUnavailableError(
            "Rendered sensitive email contains an unresolved manual placeholder"
        )
    if "styleInsert" not in html_body or "ImageServer" not in html_body:
        raise SalesforceUnavailableError(
            "Rendered sensitive email did not include the Salesforce letterhead"
        )
    _verify_agent_email_signature(preview)
    normalized_plain = _normalized_email_body(plain_body)
    for phrase in (
        "hello ",
        "dear ",
        "the nova support team",
        SUPPORT_ORG_WIDE_EMAIL_ADDRESS,
        BILLING_ORG_WIDE_EMAIL_ADDRESS,
    ):
        if normalized_plain.count(phrase) > 1:
            raise SalesforceUnavailableError(
                "Rendered sensitive email wrapper or signature was duplicated"
            )
    return {
        "verified": True,
        "subject": subject,
        "letterheadIncluded": True,
        "mergeFieldsResolved": True,
        "manualPlaceholdersResolved": True,
        "wrapperSignatureChecksPassed": True,
        "credentialMaterialReturned": False,
    }


def _stable_template_fragments(plain_body: str) -> list[str]:
    ignored = (
        "hello",
        "dear ",
        "thank you",
        "sincerely",
        "the nova support team",
        "novapos",
        "billing@",
        "(888)",
    )
    fragments: list[str] = []
    for raw_line in str(plain_body or "").splitlines():
        line = re.sub(r"\s+", " ", unescape(raw_line)).strip()
        normalized = _normalized_text(line)
        if len(line) < 24 or any(normalized.startswith(value) for value in ignored):
            continue
        fragments.append(line)
        if len(fragments) == 2:
            break
    return fragments


def _normalized_email_body(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", str(value or ""))
    return _normalized_text(unescape(without_tags))


def _ticket_template_delivery_identity(
    prepared: dict[str, Any],
    *,
    key_prefix: str,
) -> tuple[str, str, str]:
    """Build one stable operation identity from the exact approved send plan."""

    sender = dict(prepared["sender"])
    targets = dict(prepared["targets"])
    preview_summary = dict(prepared["previewSummary"])
    plan_material = json.dumps(
        {
            "ticketId": prepared["ticketId"],
            "situation": prepared["situation"],
            "templateId": prepared["templateId"],
            "subject": prepared["subject"],
            "fromAddress": str(sender["address"]).casefold(),
            "recipients": sorted(
                str(value).casefold() for value in targets["recipients"]
            ),
            "htmlSha256": preview_summary.get("htmlSha256"),
            "plainTextSha256": preview_summary.get("plainTextSha256"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    plan_hash = hashlib.sha256(plan_material.encode("utf-8")).hexdigest()
    clean_prefix = _bounded(key_prefix, "email idempotency prefix", 80)
    idempotency_key = f"{clean_prefix}:{plan_hash}"
    target = f"{prepared['ticketId']}:{prepared['templateId']}:{plan_hash[:16]}"
    return idempotency_key, target, plan_hash


def _public_ticket_template_preview(prepared: dict[str, Any]) -> dict[str, Any]:
    preview = dict(prepared["renderedPreview"])
    targets = dict(prepared["targets"])
    sender = dict(prepared["sender"])
    return {
        "ok": True,
        "verified": True,
        "sent": False,
        "writesPerformed": False,
        "ticketId": prepared["ticketId"],
        "situation": prepared["situation"],
        "templateId": prepared["templateId"],
        "templateName": prepared["templateName"],
        "templateDeveloperName": prepared["templateDeveloperName"],
        "subject": prepared["subject"],
        "plainTextBody": str(preview.get("plainTextBody") or ""),
        "primaryRecipient": targets["primaryRecipient"],
        "additionalRecipients": targets["additionalRecipients"],
        "recipients": targets["recipients"],
        "department": sender["department"],
        "senderPolicy": sender["senderPolicy"],
        "fromAddress": sender["address"],
        "validation": prepared["previewSummary"],
        "callerSelectedRecipients": False,
        "callerSelectedSubject": False,
        "callerSelectedTemplate": False,
        "freehandBodyAccepted": False,
    }


def _public_sensitive_template_preview(prepared: dict[str, Any]) -> dict[str, Any]:
    sender = dict(prepared["sender"])
    return {
        "ok": True,
        "verified": True,
        "sent": False,
        "writesPerformed": False,
        "ticketId": prepared["ticketId"],
        "ticketNumber": prepared["ticketNumber"],
        "situation": prepared["situation"],
        "templateId": prepared["templateId"],
        "templateName": prepared["templateName"],
        "templateDeveloperName": prepared["templateDeveloperName"],
        "subject": prepared["subject"],
        "recipients": list(prepared["recipients"]),
        "department": sender["department"],
        "senderPolicy": sender["senderPolicy"],
        "fromAddress": sender["address"],
        "sensitivity": "credential_secret",
        "validation": dict(prepared["validation"]),
        "credentialMaterialReturned": False,
        "bodyReturned": False,
        "fingerprintsReturned": False,
        "arbitraryRecipientsAccepted": False,
        "callerSelectedSubject": False,
        "callerSelectedTemplate": False,
        "callerSelectedSender": False,
        "freehandBodyAccepted": False,
    }


def _public_sensitive_delivery_receipt(
    prepared: dict[str, Any],
    readback: dict[str, dict[str, Any]],
    *,
    idempotency_key: str,
    sent: bool,
    duplicate: bool,
) -> dict[str, Any]:
    preview = _public_sensitive_template_preview(prepared)
    recipients = [str(value) for value in prepared["recipients"]]
    return {
        **preview,
        "accepted": True,
        "sent": sent,
        "writesPerformed": sent,
        "duplicate": duplicate,
        "deliveryVerified": True,
        "idempotencyKey": idempotency_key,
        "emailMessages": [
            _public_email_record(readback[recipient.casefold()])
            for recipient in recipients
        ],
    }


def _verify_amount_template_preview(
    preview: dict[str, str],
    *,
    expected_amount: str,
    brand_template_id: str,
    expected_subject: str,
    amount_result_key: str,
) -> dict[str, Any]:
    subject = str(preview.get("subject") or "").strip()
    html_body = str(preview.get("htmlBody") or "")
    plain_body = str(preview.get("plainTextBody") or "")
    if subject != expected_subject:
        raise SalesforceUnavailableError("Rendered billing email subject did not match policy")
    if not html_body.strip() or not plain_body.strip():
        raise SalesforceUnavailableError("Rendered billing email is missing HTML or plain-text content")
    for marker in ("{!", "{{", "}}", "]]>"):
        if marker in html_body or marker in plain_body:
            raise SalesforceUnavailableError("Rendered billing email contains unresolved template content")
    currency_pattern = re.compile(r"\$\d[\d,]*\.\d{2}")
    html_amounts = set(currency_pattern.findall(html_body))
    plain_amounts = set(currency_pattern.findall(plain_body))
    if html_amounts != {expected_amount} or plain_amounts != {expected_amount}:
        raise SalesforceUnavailableError("Rendered billing email amount did not match the verified amount")
    if plain_body.count("Hello,") != 1 or plain_body.count("Nova POS Team") != 1:
        raise SalesforceUnavailableError("Rendered billing email greeting or signature was duplicated")
    if "styleInsert" not in html_body or "ImageServer" not in html_body:
        raise SalesforceUnavailableError("Rendered billing email did not include the Salesforce letterhead")
    _verify_agent_email_signature(preview, required_signature="Nova POS Team")
    return {
        "verified": True,
        "subject": subject,
        amount_result_key: expected_amount,
        "brandTemplateId": brand_template_id,
        "htmlLength": len(html_body),
        "plainTextLength": len(plain_body),
        "letterheadIncluded": True,
        "mergeFieldsResolved": True,
    }


def _feed_element_text(element: Any) -> str:
    if not isinstance(element, dict):
        return ""
    body = element.get("body") if isinstance(element.get("body"), dict) else {}
    text = unescape(str(body.get("text") or "")).strip()
    if text:
        return text
    segments = body.get("messageSegments") if isinstance(body.get("messageSegments"), list) else []
    return unescape(
        "".join(
            str(segment.get("text") or "")
            for segment in segments
            if isinstance(segment, dict)
        )
    ).strip()


def _matching_feed_element(elements: Any, body: str) -> dict[str, Any] | None:
    if not isinstance(elements, list):
        return None
    expected = _normalized_text(body)
    for element in elements:
        if isinstance(element, dict) and _normalized_text(_feed_element_text(element)) == expected:
            return element
    return None


def _feed_element_comments(element: Any) -> list[dict[str, Any]]:
    if not isinstance(element, dict):
        return []
    capabilities = element.get("capabilities")
    capabilities = capabilities if isinstance(capabilities, dict) else {}
    comments = capabilities.get("comments")
    comments = comments if isinstance(comments, dict) else {}
    page = comments.get("page")
    page = page if isinstance(page, dict) else {}
    items = page.get("items")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _feed_element_by_id(elements: Any, feed_element_id: str) -> dict[str, Any] | None:
    if not isinstance(elements, list):
        return None
    expected = str(feed_element_id or "").strip()
    for element in elements:
        if isinstance(element, dict) and str(element.get("id") or "").strip() == expected:
            return element
    return None


def _matching_feed_comment(
    elements: Any,
    body: str,
    *,
    parent_feed_element_id: str = "",
) -> dict[str, Any] | None:
    if not isinstance(elements, list):
        return None
    expected = _normalized_text(body)
    expected_parent = str(parent_feed_element_id or "").strip()
    for element in elements:
        if not isinstance(element, dict):
            continue
        if expected_parent and str(element.get("id") or "").strip() != expected_parent:
            continue
        for comment in _feed_element_comments(element):
            if _normalized_text(_feed_element_text(comment)) == expected:
                return comment
    return None


def _matching_ticket_feed_entry(elements: Any, body: str) -> dict[str, Any] | None:
    """Match an exact prior outcome across both posts and nested replies."""

    return _matching_feed_element(elements, body) or _matching_feed_comment(elements, body)


def _matching_mentioned_feed_element(
    elements: Any,
    *,
    recipient_id: str,
    message: str,
) -> dict[str, Any] | None:
    if not isinstance(elements, list):
        return None
    expected = _normalized_text(message)
    for element in elements:
        if not isinstance(element, dict):
            continue
        body = element.get("body") if isinstance(element.get("body"), dict) else {}
        segments = (
            body.get("messageSegments")
            if isinstance(body.get("messageSegments"), list)
            else []
        )
        mentioned = any(
            isinstance(segment, dict)
            and _normalized_text(str(segment.get("type") or "")) == "mention"
            and str(
                segment.get("id")
                or (
                    segment.get("record", {}).get("id")
                    if isinstance(segment.get("record"), dict)
                    else ""
                )
                or ""
            ).strip()
            == recipient_id
            for segment in segments
        )
        if not mentioned:
            continue
        rendered = _normalized_text(_feed_element_text(element))
        text_only = _normalized_text(
            "".join(
                str(segment.get("text") or "")
                for segment in segments
                if isinstance(segment, dict)
                and _normalized_text(str(segment.get("type") or "")) == "text"
            )
        )
        if rendered.endswith(expected) or text_only.endswith(expected):
            return element
    return None


def _email_action_succeeded(value: Any) -> bool:
    rows = value if isinstance(value, list) else [value]
    return bool(rows) and all(isinstance(row, dict) and row.get("isSuccess") is True for row in rows)


def _email_action_error_codes(value: Any) -> str:
    rows = value if isinstance(value, list) else [value]
    codes: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        errors = row.get("errors")
        if not isinstance(errors, list):
            continue
        for error in errors:
            if not isinstance(error, dict):
                continue
            code = str(error.get("statusCode") or error.get("errorCode") or "").strip()
            if code and re.fullmatch(r"[A-Z0-9_]{2,80}", code):
                codes.append(code)
    return ",".join(dict.fromkeys(codes)) or "ACTION_FAILED"


def _canonical_mailbox_address(value: Any) -> str | None:
    """Return one normalized addr-spec after strict structural validation."""

    address = str(value or "").strip()
    if (
        not address
        or len(address) > 254
        or not EMAIL.fullmatch(address)
    ):
        return None
    local, domain = address.rsplit("@", 1)
    if (
        not local
        or len(local) > 64
        or local.startswith(".")
        or local.endswith(".")
        or ".." in local
        or not domain
        or len(domain) > 253
        or domain.endswith(".")
    ):
        return None
    normalized_domain = domain.casefold()
    labels = normalized_domain.split(".")
    if len(labels) < 2 or any(
        not re.fullmatch(
            r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
            label,
        )
        for label in labels
    ):
        return None
    return f"{local.casefold()}@{normalized_domain}"


def _canonical_mailbox_list(
    value: Any,
    *,
    allow_semicolon_separator: bool = False,
) -> frozenset[str]:
    """Parse actual header mailboxes and fail closed on any malformed member."""

    raw = str(value or "").strip()
    if not raw or any(character in raw for character in ("\r", "\n", "\x00")):
        return frozenset()
    if allow_semicolon_separator:
        # Salesforce commonly serializes EmailMessage.ToAddress lists with
        # semicolons. Convert only the list separator before using the stdlib's
        # strict RFC mailbox parser; display-name text never becomes an address.
        raw = raw.replace(";", ",")
    parsed = getaddresses([raw])
    if not parsed:
        return frozenset()
    canonical: list[str] = []
    for _display_name, address in parsed:
        mailbox = _canonical_mailbox_address(address)
        if not mailbox:
            return frozenset()
        canonical.append(mailbox)
    header_mailboxes = _header_mailboxes("To", raw)
    if header_mailboxes is None or tuple(canonical) != header_mailboxes:
        return frozenset()
    return frozenset(canonical)


def _canonical_single_mailbox(value: Any) -> str | None:
    """Parse exactly one unambiguous mailbox and return its normalized addr-spec."""

    raw = str(value or "").strip()
    if not raw or any(character in raw for character in ("\r", "\n", "\x00")):
        return None
    if ";" in raw or raw.startswith(",") or raw.endswith(","):
        return None
    parsed = getaddresses([raw])
    _display_name, parseaddr_mailbox = parseaddr(raw)
    if (
        len(parsed) != 1
        or not parsed[0][1]
        or not parseaddr_mailbox
        or parsed[0][1] != parseaddr_mailbox
    ):
        return None
    mailbox = _canonical_mailbox_address(parseaddr_mailbox)
    header_mailboxes = _header_mailboxes("From", raw)
    if not mailbox or header_mailboxes != (mailbox,):
        return None
    return mailbox


def _header_mailboxes(field_name: str, value: str) -> tuple[str, ...] | None:
    """Require the stdlib structured header parser to report no syntax defects."""

    try:
        message = HeaderParser(policy=email_policy.default).parsestr(
            f"{field_name}: {value}\n\n",
            headersonly=True,
        )
        header = message[field_name]
        if header is None or header.defects:
            return None
        canonical: list[str] = []
        for address in header.addresses:
            mailbox = _canonical_mailbox_address(address.addr_spec)
            if not mailbox:
                return None
            canonical.append(mailbox)
        return tuple(canonical)
    except (AttributeError, IndexError, TypeError, ValueError):
        return None


def _is_nova_email_domain(address: str) -> bool:
    domain = str(address or "").rsplit("@", 1)[-1].casefold()
    return (
        domain == "novapointofsale.com"
        or domain.endswith(".novapointofsale.com")
    )


def _verified_ticket_additional_emails(
    ticket: dict[str, Any],
    *,
    exclude: Collection[str] = (),
) -> list[str]:
    """Return only ticket recipients backed by explicit positive send evidence."""

    excluded = {str(value or "").strip().casefold() for value in exclude}
    structured_fields = (
        "Email_Address_to_Send_Ticket__c",
        "Account_s_Email_Address__c",
    )
    fields = (
        *structured_fields,
        "Description__c",
        "Notes_Send_To_Client__c",
    )
    positive_action = re.compile(
        r"\b(?:send|deliver|notify|copy|cc|include)\b"
        r"|\brequest(?:ed|s|ing)?\b.{0,60}"
        r"\b(?:notice|notification|email|copy|delivery)\b",
        re.IGNORECASE,
    )
    negation = re.compile(
        r"\b(?:do\s+not|don['’]?t|dont|never|not|exclude(?:d)?|"
        r"remove|wrong|instead|ignore)\b",
        re.IGNORECASE,
    )
    quoted_or_signature = re.compile(
        r"^\s*(?:from|sent|to|cc|bcc|subject|reply-to|email)\s*:"
        r"|\b(?:quoted|forwarded|original\s+message|email\s+history|"
        r"vendor\s+history|signature)\b",
        re.IGNORECASE | re.MULTILINE,
    )
    intent_boundary = re.compile(
        r"(?:\s+(?:and|but)\s+|,\s*)"
        r"(?=(?:do\s+not|don['’]?t|dont|never|not|exclude(?:d)?|"
        r"remove|wrong|instead|ignore|send|deliver|notify|copy|cc|"
        r"include|email)\b)",
        re.IGNORECASE,
    )

    def clean_external_candidates(value: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for candidate in EMAIL_IN_TEXT.findall(value):
            clean = candidate.strip().rstrip(".,;:)>]}").lstrip("(<[{")
            key = clean.casefold()
            if (
                not EMAIL.fullmatch(clean)
                or key in excluded
                or key.endswith("@novapointofsale.com")
            ):
                continue
            result.setdefault(key, clean)
        return result

    def is_plain_structured_list(value: str) -> bool:
        tokens = EMAIL_IN_TEXT.findall(value)
        if not tokens:
            return False
        remainder = EMAIL_IN_TEXT.sub("", value)
        return not remainder.strip(" \t\r\n,;|")

    approved: dict[str, str] = {}
    explicit_exclusions: set[str] = set()
    for field in fields:
        value = str(ticket.get(field) or "")
        field_candidates = clean_external_candidates(value)
        if not field_candidates:
            continue
        plain_structured = (
            field in structured_fields and is_plain_structured_list(value)
        )
        untrusted_block = (
            field not in structured_fields
            and quoted_or_signature.search(value) is not None
        )
        for clause in _credential_evidence_clauses(value):
            for segment in intent_boundary.split(clause):
                segment_candidates = clean_external_candidates(segment)
                if not segment_candidates:
                    continue
                keys = set(segment_candidates)
                if negation.search(segment):
                    explicit_exclusions.update(keys)
                    continue
                if untrusted_block or quoted_or_signature.search(segment):
                    continue
                intent_text = EMAIL_IN_TEXT.sub("__RECIPIENT__", segment)
                if plain_structured or positive_action.search(intent_text):
                    for key, candidate in segment_candidates.items():
                        approved.setdefault(key, candidate)

    result: dict[str, str] = {}
    for key, candidate in approved.items():
        if key in explicit_exclusions:
            continue
        clean = candidate.strip().rstrip(".,;:)>]}").lstrip("(<[{")
        result.setdefault(key, clean)
    return [result[key] for key in sorted(result)]


def _credential_evidence_clauses(value: Any) -> list[str]:
    """Split ticket evidence without treating dots inside email addresses as stops."""

    replacements: dict[str, str] = {}

    def replace_email(match: re.Match[str]) -> str:
        token = f"__NOVA_EMAIL_{len(replacements)}__"
        replacements[token] = match.group(0)
        return token

    masked = EMAIL_IN_TEXT.sub(replace_email, str(value or ""))
    clauses = re.split(r"(?:[\r\n]+|(?<=[.!?;])\s+)", masked)
    restored: list[str] = []
    for clause in clauses:
        clean = clause.strip()
        for token, address in replacements.items():
            clean = clean.replace(token, address)
        if clean:
            restored.append(clean)
    return restored


def _positive_credentials_recipient_evidence(ticket: dict[str, Any]) -> set[str]:
    """Return authorized recipients supported by explicit positive ticket evidence."""

    authorized = {
        value.casefold() for value in CREDENTIALS_AUTHORIZED_RECIPIENTS
    }
    positive_action = re.compile(
        r"\b(?:send|deliver|email|provide|share|request(?:ed)?|approve(?:d)?|authorize(?:d)?)\b",
        re.IGNORECASE,
    )
    credential_context = re.compile(
        r"\b(?:credential(?:s)?|login|username|password|access)\b",
        re.IGNORECASE,
    )
    negation = re.compile(
        r"\b(?:do\s+not|don['’]?t|dont|never|not|exclude(?:d)?|remove|wrong|instead)\b",
        re.IGNORECASE,
    )
    evidence: set[str] = set()
    explicit_exclusions: set[str] = set()
    for field in CREDENTIALS_RECIPIENT_EVIDENCE_FIELDS:
        for clause in _credential_evidence_clauses(ticket.get(field)):
            addresses = {
                value.casefold() for value in EMAIL_IN_TEXT.findall(clause)
            }
            candidates = addresses.intersection(authorized)
            if not candidates:
                continue
            if negation.search(clause):
                explicit_exclusions.update(candidates)
                continue
            if field == "Email_Address_to_Send_Ticket__c" or (
                positive_action.search(clause) and credential_context.search(clause)
            ):
                evidence.update(candidates)
    # Fail closed when an authorized address is also explicitly excluded
    # anywhere in the bounded ticket evidence. A stale positive mention must
    # not override a correction, and a later positive mention cannot silently
    # erase an unresolved exclusion without operator-cleaned evidence.
    return evidence.difference(explicit_exclusions)


def _validated_credentials_recipients(values: list[str]) -> list[str]:
    if not isinstance(values, list):
        raise SalesforceScopeError("requested_recipients must be an exact email list")
    cleaned = [str(value or "").strip() for value in values]
    if (
        len(cleaned) != len(CREDENTIALS_AUTHORIZED_RECIPIENTS)
        or any(not EMAIL.fullmatch(value) for value in cleaned)
        or len({value.casefold() for value in cleaned}) != len(cleaned)
    ):
        raise SalesforceScopeError(
            "requested_recipients must contain the exact two authorized ticket 347370 addresses"
        )
    requested = {value.casefold() for value in cleaned}
    if requested.intersection(CREDENTIALS_EXCLUDED_RECIPIENTS):
        raise SalesforceScopeError(
            "requested_recipients contains an explicitly excluded ticket 347370 address"
        )
    authorized = {value.casefold() for value in CREDENTIALS_AUTHORIZED_RECIPIENTS}
    if requested != authorized:
        raise SalesforceScopeError(
            "requested_recipients must contain the exact two authorized ticket 347370 addresses"
        )
    return list(CREDENTIALS_AUTHORIZED_RECIPIENTS)


def _salesforce_error_codes(response: requests.Response) -> str:
    try:
        value = response.json()
    except (TypeError, ValueError):
        return "UNKNOWN_ERROR"
    rows = value if isinstance(value, list) else [value]
    codes: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("errorCode") or row.get("statusCode") or "").strip()
        if code and re.fullmatch(r"[A-Z0-9_]{2,80}", code):
            codes.append(code)
    return ",".join(dict.fromkeys(codes)) or "UNKNOWN_ERROR"


def _salesforce_error_summary(response: requests.Response) -> str:
    """Return bounded Salesforce codes and messages without leaking record identifiers."""

    codes = _salesforce_error_codes(response)
    try:
        value = response.json()
    except (TypeError, ValueError):
        return codes
    rows = value if isinstance(value, list) else [value]
    messages: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        message = re.sub(r"\s+", " ", str(row.get("message") or "")).strip()
        if not message:
            continue
        message = re.sub(
            r"\b(?:001|003|a0[A-Za-z0-9])[A-Za-z0-9]{12,15}\b",
            "[record]",
            message,
        )
        messages.append(message[:500])
    unique_messages = list(dict.fromkeys(messages))[:3]
    if not unique_messages:
        return codes
    return f"{codes}: {' | '.join(unique_messages)}"


def _public_email_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _bounded_record(record.get(key))
        for key in (
            "Id",
            "Subject",
            "ToAddress",
            "Status",
            "MessageDate",
            "RelatedToId",
            "FromAddress",
            "CreatedDate",
            "Incoming",
        )
        if key in record
    }


def _require_email_readback_sender(
    records: Collection[dict[str, Any]],
    expected_from_address: str,
) -> None:
    expected = str(expected_from_address or "").strip().casefold()
    if not expected or any(
        str(record.get("FromAddress") or "").strip().casefold() != expected
        for record in records
    ):
        raise SalesforceUnavailableError(
            "Salesforce EmailMessage FromAddress did not match department sender policy; do not retry"
        )


def _required_email_lane(value: str) -> str:
    clean = str(value or "").strip()
    if clean not in {"direct_codex", "coding_agent", "tickets_agent", "billing_agent"}:
        raise SalesforceScopeError("email operation requires a fixed approved agent lane")
    return clean


def _required_id(value: str, label: str) -> str:
    clean = str(value or "").strip()
    if not SALESFORCE_ID.fullmatch(clean):
        raise SalesforceScopeError(f"{label} must be a Salesforce record id")
    return clean


def _weekly_utc_timestamp(value: str, label: str) -> tuple[str, datetime]:
    clean = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SalesforceScopeError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise SalesforceScopeError(f"{label} must include a timezone")
    normalized = parsed.astimezone(timezone.utc).replace(microsecond=0)
    return normalized.strftime("%Y-%m-%dT%H:%M:%SZ"), normalized


def _optional_id(value: str, label: str) -> str:
    clean = str(value or "").strip()
    return _required_id(clean, label) if clean else ""


def _bounded(value: Any, label: str, maximum: int) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > maximum:
        raise SalesforceScopeError(f"{label} must be between 1 and {maximum} characters")
    return clean


def _put_optional_id(payload: dict[str, Any], field: str, value: str) -> None:
    clean = _optional_id(value, field)
    if clean:
        payload[field] = clean


def _put_optional_text(payload: dict[str, Any], field: str, value: str, maximum: int) -> None:
    if str(value or "").strip():
        payload[field] = _bounded(value, field, maximum)


def _allowlisted_fields(fields: dict[str, Any], allowed: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(fields, dict) or not fields:
        raise SalesforceScopeError(f"{label} fields are required")
    unknown = set(fields) - allowed
    if unknown:
        raise SalesforceScopeError(f"{label} field is not allowed")
    payload = {key: value for key, value in fields.items() if value is not None}
    if not payload:
        raise SalesforceScopeError(f"{label} fields are empty")
    for key, value in payload.items():
        if isinstance(value, str) and len(value) > 131072:
            raise SalesforceScopeError(f"{label} field value is too large")
        if key.endswith("Id") or (key.endswith("__c") and key in {
            "Account__c",
            "Contact__c",
            "NovaPOS_Location__c",
            "NovaPOS_Billing_Schedule__c",
        }):
            payload[key] = _required_id(str(value), key)
    return payload


def _bounded_record(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return "<truncated>"
    if isinstance(value, dict):
        return {
            str(key)[:200]: _bounded_record(child, depth + 1)
            for key, child in list(value.items())[:200]
            if str(key).lower() != "attributes"
        }
    if isinstance(value, list):
        return [_bounded_record(child, depth + 1) for child in value[:200]]
    if isinstance(value, str):
        return value[:131072]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:2000]


def _feed_body_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()[:20000]
    if not isinstance(value, dict):
        return ""
    text = str(value.get("text") or "").strip()
    if text:
        return text[:20000]
    segments = value.get("messageSegments")
    if not isinstance(segments, list):
        return ""
    return "".join(
        str(segment.get("text") or "")
        for segment in segments[:100]
        if isinstance(segment, dict)
    ).strip()[:20000]


def _compact_feed_actor(value: Any) -> dict[str, Any]:
    actor = value if isinstance(value, dict) else {}
    return {
        "id": str(actor.get("id") or "")[:40],
        "name": str(
            actor.get("displayName") or actor.get("name") or ""
        ).strip()[:255],
        "active": actor.get("isActive") if isinstance(actor.get("isActive"), bool) else None,
    }


def _compact_ticket_feed(elements: Any) -> list[dict[str, Any]]:
    """Project exact post/comment text without unrelated Chatter profile data."""

    compact: list[dict[str, Any]] = []
    for raw in elements if isinstance(elements, list) else []:
        if not isinstance(raw, dict):
            continue
        capabilities = raw.get("capabilities")
        capabilities = capabilities if isinstance(capabilities, dict) else {}
        tracked = capabilities.get("trackedChanges")
        tracked = tracked if isinstance(tracked, dict) else {}
        comments_capability = capabilities.get("comments")
        comments_capability = (
            comments_capability if isinstance(comments_capability, dict) else {}
        )
        page = comments_capability.get("page")
        page = page if isinstance(page, dict) else {}
        comments: list[dict[str, Any]] = []
        for comment in page.get("items", []) if isinstance(page.get("items"), list) else []:
            if not isinstance(comment, dict):
                continue
            comments.append(
                {
                    "id": str(comment.get("id") or "")[:40],
                    "createdDate": str(comment.get("createdDate") or "")[:64],
                    "author": _compact_feed_actor(comment.get("user")),
                    "text": _feed_body_text(comment.get("body")),
                }
            )
        compact.append(
            {
                "id": str(raw.get("id") or "")[:40],
                "type": str(raw.get("type") or raw.get("feedElementType") or "")[:80],
                "createdDate": str(raw.get("createdDate") or "")[:64],
                "visibility": str(raw.get("visibility") or "")[:80],
                "author": _compact_feed_actor(raw.get("actor")),
                "text": _feed_body_text(raw.get("body")),
                "trackedChanges": _bounded_record(tracked.get("changes") or []),
                "comments": comments[:100],
            }
        )
    return compact[:20]
