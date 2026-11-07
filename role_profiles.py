"""Host-owned presentation profiles. These never authorize an API operation."""

import re


DISPLAY_MODES = ("basic", "operations", "finance")
MODE_RANK = {mode: index for index, mode in enumerate(DISPLAY_MODES)}

# Keep in sync with the explicit client presentation keys in src/interface_mode.js.
DISPLAY_FEATURE_TIERS = {
    "workspaceSwitch": "basic", "projects": "basic", "boards": "basic",
    "cards": "basic", "createTask": "basic", "createProject": "basic",
    "createBoard": "basic", "assignees": "basic", "dueDate": "basic",
    "reminder": "basic", "priority": "basic", "search": "basic",
    "quickFilters": "basic", "taskTrash": "basic", "projectFiles": "basic",
    "cardChecklist": "basic", "cardAttachments": "basic", "boardView": "basic",
    "listView": "basic", "syncStatus": "basic", "backupRestore": "basic",
    "networkStatus": "basic", "settings": "basic", "profile": "basic",
    "notifications": "basic", "workspaceManagement": "operations",
    "boardAdministration": "operations", "projectAdministration": "operations",
    "advancedFilters": "operations", "activity": "operations",
    "reporting": "operations", "planner": "operations",
    "timeDashboard": "operations", "timelineView": "operations",
    "taskTime": "operations", "cardComments": "operations",
    "customFields": "operations", "boardFieldEditor": "operations",
    "automationRules": "operations", "trelloImport": "operations",
    "calendarInterop": "operations", "secureApiKeys": "operations",
    "lanUserManagement": "operations", "financeHub": "finance",
    "projectFinance": "finance", "profitPeek": "finance",
    "taskCostControls": "finance", "checklistCostControls": "finance",
    "projectPricing": "finance", "accountingDashboard": "finance", "aiAgent": "finance",
}

BUILTIN_LABELS = {
    "superadmin": "مدیرکل", "senior": "مدیر ارشد", "middle": "مدیر میانی",
    "unit": "مدیر واحد", "employee": "کارمند",
}
LEGACY_DISPLAY_ROLE = {"admin": "superadmin", "editor": "middle", "viewer": "employee"}
MAX_ROLES = 32
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")


def mode_features(mode):
    return [name for name, tier in DISPLAY_FEATURE_TIERS.items()
            if MODE_RANK[tier] <= MODE_RANK[mode]]


def default_roles():
    standard_operations = mode_features("operations")
    return {
        "superadmin": {"id": "superadmin", "label": BUILTIN_LABELS["superadmin"],
                       "displayMode": "finance", "features": mode_features("finance")},
        "senior": {"id": "senior", "label": BUILTIN_LABELS["senior"],
                   "displayMode": "operations", "features": standard_operations},
        "middle": {"id": "middle", "label": BUILTIN_LABELS["middle"],
                   "displayMode": "operations", "features": [feature for feature in standard_operations
                        if feature not in {"secureApiKeys", "lanUserManagement"}]},
        "unit": {"id": "unit", "label": BUILTIN_LABELS["unit"],
                 "displayMode": "operations", "features": [feature for feature in standard_operations
                    if feature not in {"secureApiKeys", "lanUserManagement", "automationRules",
                                       "trelloImport", "boardFieldEditor"}]},
        "employee": {"id": "employee", "label": BUILTIN_LABELS["employee"],
                     "displayMode": "basic", "features": mode_features("basic")},
    }


def validate_role(payload):
    if type(payload) is not dict or set(payload) != {"id", "label", "displayMode", "features"}:
        raise ValueError("Role requires id, label, displayMode and features")
    identifier, label = payload["id"], payload["label"]
    if type(identifier) is not str or not ID_PATTERN.fullmatch(identifier):
        raise ValueError("Display role id must be 2-32 lowercase ASCII characters")
    if (type(label) is not str or not 1 <= len(label.strip()) <= 60 or
            any(ord(character) < 32 or ord(character) == 127 for character in label)):
        raise ValueError("Display role label must be 1-60 printable characters")
    mode, features = payload["displayMode"], payload["features"]
    if type(mode) is not str or mode not in MODE_RANK:
        raise ValueError("Unknown presentation mode")
    if (type(features) is not list or len(features) > len(DISPLAY_FEATURE_TIERS) or
            any(type(feature) is not str or feature not in DISPLAY_FEATURE_TIERS or
                MODE_RANK[DISPLAY_FEATURE_TIERS.get(feature, "finance")] > MODE_RANK[mode]
                for feature in features) or len(features) != len(set(features))):
        raise ValueError("Invalid or out-of-tier presentation features")
    return {"id": identifier, "label": label.strip(), "displayMode": mode,
            "features": [name for name in DISPLAY_FEATURE_TIERS if name in features]}


def public_role(role):
    return {**role, "features": list(role["features"]),
            "isBuiltin": role["id"] in BUILTIN_LABELS}


def effective_display(account, roles=None):
    """Calculate display settings without ever changing account['role'] / server ACL."""
    roles = roles or default_roles()
    fallback = LEGACY_DISPLAY_ROLE.get(account.get("role"), "employee")
    identifier = account.get("displayRole", fallback)
    if type(identifier) is not str or identifier not in roles:
        identifier = fallback
    role = roles[identifier]
    mode = account.get("displayMode", role["displayMode"])
    if type(mode) is not str or mode not in MODE_RANK or MODE_RANK[mode] > MODE_RANK[role["displayMode"]]:
        mode = role["displayMode"]
    allowed = [feature for feature in role["features"]
               if MODE_RANK[DISPLAY_FEATURE_TIERS[feature]] <= MODE_RANK[mode]]
    selected = account.get("displayFeatures", allowed)
    if (type(selected) is not list or len(selected) > len(DISPLAY_FEATURE_TIERS) or
            any(type(feature) is not str for feature in selected)):
        selected = []
    return {"displayRole": identifier, "displayMode": mode,
            "displayRoleLabel": role["label"],
            "displayFeatures": [feature for feature in allowed if feature in selected]}
