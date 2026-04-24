document.addEventListener("DOMContentLoaded", function () {
    const presetsNode = document.getElementById("scenario-presets-data");

    if (!presetsNode) {
        return;
    }

    const presets = JSON.parse(presetsNode.textContent);

    const constructorCheckboxNames = [
        "track_leads",
        "track_complaints",
        "track_requests",
        "track_urgent",
        "track_general_activity",
        "ignore_greetings",
        "ignore_short_replies",
        "ignore_emojis",
        "urgent_negative",
        "urgent_deadlines",
        "urgent_repeated_messages",
        "extract_name",
        "extract_contact",
        "extract_budget",
        "extract_product_or_service",
        "extract_date_or_time",
    ];

    function applyScenarioPreset(form, scenarioValue) {
        if (!scenarioValue || scenarioValue === "custom") {
            return;
        }

        const preset = presets[scenarioValue];

        if (!preset) {
            return;
        }

        constructorCheckboxNames.forEach(function (fieldName) {
            const input = form.querySelector(`[name="${fieldName}"]`);

            if (!input || input.type !== "checkbox") {
                return;
            }

            if (Object.prototype.hasOwnProperty.call(preset, fieldName)) {
                input.checked = Boolean(preset[fieldName]);
            }
        });
    }

    document.querySelectorAll(".profile-create-form").forEach(function (form) {
        const scenarioField = form.querySelector('[name="scenario"]');

        if (!scenarioField) {
            return;
        }

        scenarioField.addEventListener("change", function () {
            applyScenarioPreset(form, scenarioField.value);
        });
    });
});

document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-digest-settings]").forEach(function (root) {
        const checkbox = root.querySelector(
            "[data-digest-enabled], input[name='digest_enabled']"
        );
        const frequencyWrapper = root.querySelector("[data-digest-frequency]");
        const frequencyInput = root.querySelector(
            "[data-digest-interval], select[name='digest_interval_hours'], input[name='digest_interval_hours']"
        );

        if (!checkbox || !frequencyWrapper || !frequencyInput) {
            return;
        }

        function syncDigestFrequency() {
            const enabled = checkbox.checked;

            frequencyInput.disabled = !enabled;
            frequencyWrapper.classList.toggle("is-disabled", !enabled);
            frequencyWrapper.setAttribute("aria-disabled", String(!enabled));
        }

        checkbox.addEventListener("change", syncDigestFrequency);
        syncDigestFrequency();
    });
});
