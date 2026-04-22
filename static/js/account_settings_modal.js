
document.addEventListener("DOMContentLoaded", function () {
    const openButtons = document.querySelectorAll("[data-modal-open]");
    const closeButtons = document.querySelectorAll("[data-modal-close]");

    function openModal(modalId) {
        const modal = document.getElementById(modalId);

        if (!modal) {
            return;
        }

        modal.classList.add("is-open");
        modal.setAttribute("aria-hidden", "false");
        document.body.classList.add("modal-open");
    }

    function closeModal(modal) {
        modal.classList.remove("is-open");
        modal.setAttribute("aria-hidden", "true");
        document.body.classList.remove("modal-open");
    }

    openButtons.forEach(function (button) {
        button.addEventListener("click", function () {
            openModal(button.dataset.modalOpen);
        });
    });

    closeButtons.forEach(function (button) {
        button.addEventListener("click", function () {
            const modal = button.closest(".modal");

            if (modal) {
                closeModal(modal);
            }
        });
    });

    document.addEventListener("keydown", function (event) {
        if (event.key !== "Escape") {
            return;
        }

        document.querySelectorAll(".modal.is-open").forEach(closeModal);
    });

    document.querySelectorAll("[data-delete-account-form]").forEach(function (form) {
        form.addEventListener("submit", function (event) {
            const message = form.dataset.confirmMessage || "Delete account permanently?";

            if (!window.confirm(message)) {
                event.preventDefault();
            }
        });
    });
});
