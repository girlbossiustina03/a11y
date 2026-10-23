#!/bin/sh
# One-time setup: a private code-signing certificate so every A11y build has the same identity.
#
# Unsigned (ad-hoc) builds look like a brand-new app to macOS after every update, so the
# Accessibility, Screen Recording and Automation switches turned on for the old build stop
# applying. Signed with this certificate, macOS keeps them.
#
# Run on your Mac:   sh packaging/make_signing_certificate.sh
# Then add the two printed values as repository secrets (GitHub → Settings → Secrets and
# variables → Actions): MACOS_SIGNING_P12 and MACOS_SIGNING_PASSWORD.
# Keep the secret private: anyone holding it could sign apps that macOS treats as A11y.
set -eu
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
password="$(openssl rand -hex 16)"
cat > "$work/cert.cnf" <<'EOF'
[req]
distinguished_name = dn
x509_extensions = ext
prompt = no
[dn]
CN = A11y Local Signing
[ext]
basicConstraints = critical,CA:false
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
EOF
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -config "$work/cert.cnf" \
    -keyout "$work/key.pem" -out "$work/cert.pem" 2>/dev/null
openssl pkcs12 -export -inkey "$work/key.pem" -in "$work/cert.pem" -name "A11y Local Signing" \
    -out "$work/a11y-signing.p12" -passout "pass:$password"
echo
echo "MACOS_SIGNING_PASSWORD:"
echo "$password"
echo
echo "MACOS_SIGNING_P12:"
base64 < "$work/a11y-signing.p12" | tr -d '\n'
echo
echo
echo "Add both as repository secrets, then publish a new version. After installing it, turn"
echo "A11y on once more in Privacy & Security; from then on updates keep that switch."
