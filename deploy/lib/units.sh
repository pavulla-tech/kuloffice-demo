# The stack's deploy units: one per repository, shipped by that repository's
# tags. Sourced by ci/build.sh (what to build) and bin/kulpay (what to deploy).
#
# A unit's images all carry the repository's tag. Its data is what a reset (a
# new patch or minor version) wipes, and its dependents are the units whose
# data refers to it and is wiped with it.

UNITS="keycloak kuloffice web fileserver solange kulportal"

is_unit() { case " $UNITS " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

# The .env prefixes of the unit's images (KEYCLOAK → KEYCLOAK_IMAGE/_TAG).
unit_images() {
  case $1 in
    keycloak) echo "KEYCLOAK TOKEN_PANEL TOOLS" ;;
    kuloffice) echo "KULOFFICE" ;;
    web) echo "WEB" ;;
    fileserver) echo "FILESERVER" ;;
    solange) echo "SOLANGE SOLANGE_CONSOLE" ;;
    kulportal) echo "KULPORTAL" ;;
  esac
}

# The repository checkout each unit is built from (the .env *_DIR variable).
unit_dir_var() {
  case $1 in
    keycloak) echo INTAKA_DIR ;;
    kuloffice) echo KULOFFICE_DIR ;;
    web) echo WEB_DIR ;;
    fileserver) echo FILESERVER_DIR ;;
    solange) echo SOLANGE_DIR ;;
    kulportal) echo KULPORTAL_DIR ;;
  esac
}

# The compose services recreated when the unit changes. Tools is an image
# only: `make init` runs it.
unit_services() {
  case $1 in
    keycloak) echo "keycloak token-panel" ;;
    kuloffice) echo "kuloffice" ;;
    web) echo "web" ;;
    fileserver) echo "fileserver" ;;
    solange) echo "solange solange-console" ;;
    kulportal) echo "kulportal" ;;
  esac
}

# The databases a reset of the unit wipes.
unit_databases() {
  case $1 in
    keycloak) echo "keycloak" ;;
    kuloffice) echo "kuloffice" ;;
    solange) echo "solange" ;;
  esac
}

# Units wiped with this one, because their data points into it:
#   keycloak → kuloffice: accounts hold Keycloak's user ids;
#   solange → kuloffice: its QR records point at Solange's codes (only those
#             tables are cleared, but the whole database is backed up).
unit_dependents() {
  case $1 in
    keycloak) echo "kuloffice" ;;
    solange) echo "kuloffice" ;;
  esac
}
