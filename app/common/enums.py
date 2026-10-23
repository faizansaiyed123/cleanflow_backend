import enum


class UserRole(str, enum.Enum):
    OWNER = "OWNER"
    MANAGER = "MANAGER"
    EMPLOYEE = "EMPLOYEE"
    CUSTOMER = "CUSTOMER"


class LeadSource(str, enum.Enum):
    WEBSITE = "WEBSITE"
    PHONE = "PHONE"
    WALK_IN = "WALK_IN"
    REFERRAL = "REFERRAL"
    OTHER = "OTHER"


class LeadStatus(str, enum.Enum):
    NEW = "NEW"
    CONTACTED = "CONTACTED"
    QUALIFIED = "QUALIFIED"
    QUOTED = "QUOTED"
    WON = "WON"
    LOST = "LOST"


class PropertyType(str, enum.Enum):
    OFFICE = "OFFICE"
    RETAIL = "RETAIL"
    MEDICAL = "MEDICAL"
    WAREHOUSE = "WAREHOUSE"
    RESTAURANT = "RESTAURANT"
    RESIDENTIAL = "RESIDENTIAL"
    OTHER = "OTHER"


class CleaningFrequency(str, enum.Enum):
    ONE_TIME = "ONE_TIME"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    MONTHLY = "MONTHLY"
    CUSTOM = "CUSTOM"


class QuoteStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    VIEWED = "VIEWED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ContractStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class JobStatus(str, enum.Enum):
    SCHEDULED = "SCHEDULED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class InvoiceStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    VOID = "VOID"


class PaymentMethod(str, enum.Enum):
    CASH = "CASH"
    CHECK = "CHECK"
    CREDIT_CARD = "CREDIT_CARD"
    ACH = "ACH"
    OTHER = "OTHER"


class PhotoType(str, enum.Enum):
    BEFORE = "BEFORE"
    AFTER = "AFTER"
    PROFILE = "PROFILE"
    LOGO = "LOGO"
    OTHER = "OTHER"


class NotificationType(str, enum.Enum):
    NEW_LEAD = "NEW_LEAD"
    QUOTE_CREATED = "QUOTE_CREATED"
    QUOTE_ACCEPTED = "QUOTE_ACCEPTED"
    QUOTE_REJECTED = "QUOTE_REJECTED"
    JOB_ASSIGNED = "JOB_ASSIGNED"
    JOB_RESCHEDULED = "JOB_RESCHEDULED"
    JOB_COMPLETED = "JOB_COMPLETED"
    INVOICE_CREATED = "INVOICE_CREATED"
    INVOICE_OVERDUE = "INVOICE_OVERDUE"
    CONTRACT_EXPIRING = "CONTRACT_EXPIRING"
    FEEDBACK_RECEIVED = "FEEDBACK_RECEIVED"
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED"


class InvoiceSourceType(str, enum.Enum):
    JOB = "JOB"
    CONTRACT = "CONTRACT"
    MANUAL = "MANUAL"
