#!/bin/bash

echo "Installing linters..."

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check and install PHP if needed
if ! command_exists php; then
    echo "PHP not found. Please install PHP first."
    exit 1
fi

# Check and install Node.js if needed
if ! command_exists node; then
    echo "Node.js not found. Please install Node.js first."
    exit 1
fi

# Check and install Composer if needed
if ! command_exists composer; then
    echo "Installing Composer..."
    EXPECTED_CHECKSUM="$(php -r 'copy("https://composer.github.io/installer.sig", "php://stdout");')"
    php -r "copy('https://getcomposer.org/installer', 'composer-setup.php');"
    ACTUAL_CHECKSUM="$(php -r "echo hash_file('sha384', 'composer-setup.php');")"

    if [ "$EXPECTED_CHECKSUM" != "$ACTUAL_CHECKSUM" ]; then
        echo 'ERROR: Invalid composer installer checksum'
        rm composer-setup.php
        exit 1
    fi

    php composer-setup.php --quiet
    rm composer-setup.php
    sudo mv composer.phar /usr/local/bin/composer
fi

echo "Installing PHP_CodeSniffer..."
composer global require "squizlabs/php_codesniffer=*"

echo "Installing HTMLHint..."
sudo npm install -g htmlhint

echo "Installing ESLint..."
sudo npm install -g eslint

echo "Installing Stylelint and its standard config..."
sudo npm install -g stylelint stylelint-config-standard

echo "Adding Composer's global bin directory to PATH..."
echo 'export PATH="$PATH:$HOME/.composer/vendor/bin"' >> ~/.bashrc
source ~/.bashrc

echo "Installation complete! Please restart your terminal for PATH changes to take effect."

# Verify installations
echo "Verifying installations..."
echo "PHP_CodeSniffer version:"
phpcs --version
echo "HTMLHint version:"
htmlhint --version
echo "ESLint version:"
eslint --version
echo "Stylelint version:"
stylelint --version
