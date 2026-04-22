document.addEventListener("DOMContentLoaded", function () {
    const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
    const PASSWORD_MIN_LENGTH = 8;

    function getField(form, name) {
        return form.querySelector(`[name="${name}"]`);
    }

    function getOrCreateErrorElement(input) {
        const field = input.closest(".field") || input.parentElement;
        let errorElement = field.querySelector(".client-error");

        if (!errorElement) {
            errorElement = document.createElement("div");
            errorElement.className = "client-error";
            field.appendChild(errorElement);
        }

        return errorElement;
    }

    function setFieldState(input, message) {
        const errorElement = getOrCreateErrorElement(input);

        if (message) {
            input.classList.add("is-invalid");
            input.classList.remove("is-valid");
            input.setAttribute("aria-invalid", "true");
            errorElement.textContent = message;
            return false;
        }

        input.classList.remove("is-invalid");
        input.classList.add("is-valid");
        input.setAttribute("aria-invalid", "false");
        errorElement.textContent = "";
        return true;
    }

    function clearFieldState(input) {
        const errorElement = getOrCreateErrorElement(input);

        input.classList.remove("is-invalid", "is-valid");
        input.removeAttribute("aria-invalid");
        errorElement.textContent = "";
    }

    function validateEmail(input) {
        const value = input.value.trim();

        if (!value) {
            return setFieldState(input, "Email is required.");
        }

        if (!EMAIL_RE.test(value)) {
            return setFieldState(input, "Enter a valid email address.");
        }

        return setFieldState(input, "");
    }

    function validateLoginPassword(input) {
        const value = input.value;

        if (!value) {
            return setFieldState(input, "Password is required.");
        }

        return setFieldState(input, "");
    }

    function validateSignupPassword(input) {
        const value = input.value;

        if (!value) {
            return setFieldState(input, "Password is required.");
        }

        if (value.length < PASSWORD_MIN_LENGTH) {
            return setFieldState(input, `Password must contain at least ${PASSWORD_MIN_LENGTH} characters.`);
        }

        if (/^\d+$/.test(value)) {
            return setFieldState(input, "Password cannot contain only numbers.");
        }

        return setFieldState(input, "");
    }

    function validatePasswordMatch(passwordInput, confirmationInput) {
        const password = passwordInput.value;
        const confirmation = confirmationInput.value;

        if (!confirmation) {
            return setFieldState(confirmationInput, "Repeat your password.");
        }

        if (password !== confirmation) {
            return setFieldState(confirmationInput, "Passwords do not match.");
        }

        return setFieldState(confirmationInput, "");
    }

    function attachLiveValidation(input, validator) {
        if (!input) {
            return;
        }

        input.addEventListener("input", function () {
            if (!input.value) {
                clearFieldState(input);
                return;
            }

            validator();
        });

        input.addEventListener("blur", validator);
    }

    function setupLoginForm(form) {
        const emailInput = getField(form, "login");
        const passwordInput = getField(form, "password");

        attachLiveValidation(emailInput, function () {
            return validateEmail(emailInput);
        });

        attachLiveValidation(passwordInput, function () {
            return validateLoginPassword(passwordInput);
        });

        form.addEventListener("submit", function (event) {
            const isEmailValid = validateEmail(emailInput);
            const isPasswordValid = validateLoginPassword(passwordInput);

            if (!isEmailValid || !isPasswordValid) {
                event.preventDefault();
            }
        });
    }

    function setupSignupForm(form) {
        const emailInput = getField(form, "email");
        const passwordInput = getField(form, "password1");
        const confirmationInput = getField(form, "password2");

        attachLiveValidation(emailInput, function () {
            return validateEmail(emailInput);
        });

        attachLiveValidation(passwordInput, function () {
            const isPasswordValid = validateSignupPassword(passwordInput);

            if (confirmationInput.value) {
                validatePasswordMatch(passwordInput, confirmationInput);
            }

            return isPasswordValid;
        });

        attachLiveValidation(confirmationInput, function () {
            return validatePasswordMatch(passwordInput, confirmationInput);
        });

        form.addEventListener("submit", function (event) {
            const isEmailValid = validateEmail(emailInput);
            const isPasswordValid = validateSignupPassword(passwordInput);
            const isConfirmationValid = validatePasswordMatch(passwordInput, confirmationInput);

            if (!isEmailValid || !isPasswordValid || !isConfirmationValid) {
                event.preventDefault();
            }
        });
    }

    document.querySelectorAll('[data-auth-form="login"]').forEach(setupLoginForm);
    document.querySelectorAll('[data-auth-form="signup"]').forEach(setupSignupForm);
});