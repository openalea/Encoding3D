#!/bin/bash
# Runs tutorial 2d (README.md): Java 21 and Maven; encoding3d's Java codec and GroIMP's adapter installed in Maven's
# local repository first (from the repository's root, once). Its files in outputs/.
set -euo pipefail
cd "$(dirname "$0")"
mvn -q -f ../../bindings/java/pom.xml install -DskipTests
mvn -q -f ../../bindings/java/groimp/pom.xml install -DskipTests
mvn -q compile exec:java
if command -v encoding3d > /dev/null; then encoding3d validate outputs/frames/scene.fspm.json | head -1; fi
