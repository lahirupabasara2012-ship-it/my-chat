// =========================================================
// MYCHAT - APP.JS
// Contacts + Profile Photo + New Group
// =========================================================

let currentUser = null;
let contacts = [];
let selectedGroupMembers = new Set();


// =========================================================
// API HELPER
// =========================================================

async function api(url, options = {}) {
    const response = await fetch(url, {
        credentials: "same-origin",
        ...options
    });

    let data = {};

    try {
        data = await response.json();
    } catch (e) {
        data = {};
    }

    if (!response.ok) {
        throw new Error(
            data.message || `Request failed (${response.status})`
        );
    }

    return data;
}


// =========================================================
// CURRENT USER
// =========================================================

async function loadCurrentUser() {
    try {
        const data = await api("/api/me");

        if (!data.logged_in) {
            currentUser = null;
            return false;
        }

        currentUser = data.user;

        updateProfileUI();

        return true;

    } catch (error) {
        console.error("loadCurrentUser:", error);
        return false;
    }
}


// =========================================================
// PROFILE UI
// =========================================================

function updateProfileUI() {

    if (!currentUser) {
        return;
    }

    const nameElements = document.querySelectorAll(
        "[data-current-user-name]"
    );

    nameElements.forEach(element => {
        element.textContent =
            currentUser.name || "User";
    });

    const emailElements = document.querySelectorAll(
        "[data-current-user-email]"
    );

    emailElements.forEach(element => {
        element.textContent =
            currentUser.email || "";
    });

    updateAvatarElements();
}


function updateAvatarElements() {

    if (!currentUser) {
        return;
    }

    const avatars = document.querySelectorAll(
        "[data-current-user-avatar]"
    );

    avatars.forEach(avatar => {

        if (currentUser.avatar_url) {

            avatar.innerHTML = `
                <img
                    src="${escapeHtml(currentUser.avatar_url)}"
                    alt="Profile"
                >
            `;

        } else {

            avatar.textContent =
                (currentUser.name || "U")
                .charAt(0)
                .toUpperCase();
        }
    });
}


// =========================================================
// CONTACTS
// =========================================================

async function loadContacts() {

    try {

        const data = await api("/api/contacts");

        contacts =
            Array.isArray(data.contacts)
                ? data.contacts
                : [];

        renderContacts();

    } catch (error) {

        console.error("loadContacts:", error);

        const container =
            document.getElementById("contactsList");

        if (container) {

            container.innerHTML = `
                <div class="empty-state">
                    Unable to load contacts
                </div>
            `;
        }
    }
}


function renderContacts() {

    const container =
        document.getElementById("contactsList");

    if (!container) {
        return;
    }

    if (!contacts.length) {

        container.innerHTML = `
            <div class="empty-state">
                <div style="font-size:30px;">👥</div>
                <div>No contacts yet</div>
                <small>Add a contact to start chatting.</small>
            </div>
        `;

        return;
    }

    container.innerHTML =
        contacts.map(contact => {

            const avatar =
                contact.avatar_url
                    ? `
                        <img
                            src="${escapeHtml(contact.avatar_url)}"
                            alt=""
                        >
                    `
                    : `
                        <span>
                            ${escapeHtml(
                                (contact.name || "U")
                                .charAt(0)
                                .toUpperCase()
                            )}
                        </span>
                    `;

            return `
                <div
                    class="contact-item"
                    data-contact-id="${contact.id}"
                    onclick="openPrivateChat(${contact.id})"
                >

                    <div class="contact-avatar">
                        ${avatar}
                    </div>

                    <div class="contact-info">

                        <div class="contact-name">
                            ${escapeHtml(contact.name || "Unknown")}
                        </div>

                        <div class="contact-email">
                            ${escapeHtml(contact.email || "")}
                        </div>

                    </div>

                </div>
            `;

        }).join("");
}


// =========================================================
// OPEN PRIVATE CHAT
// =========================================================

function openPrivateChat(userId) {

    const contact =
        contacts.find(
            contact =>
                Number(contact.id) === Number(userId)
        );

    if (!contact) {
        return;
    }

    console.log("Opening chat with:", contact);

    /*
       ඔයාගේ existing chat function එක තිබ්බොත්
       මෙතනින් ඒක call කරන්න.

       උදා:
       selectContact(userId);
    */

    if (typeof selectContact === "function") {
        selectContact(userId);
    }
}


// =========================================================
// ADD CONTACT
// =========================================================

async function addContact(email) {

    try {

        const data = await api(
            "/api/add-contact",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    email: email.trim()
                })
            }
        );

        if (!data.success) {
            throw new Error(
                data.message || "Could not add contact"
            );
        }

        await loadContacts();

        return true;

    } catch (error) {

        console.error("addContact:", error);

        alert(error.message);

        return false;
    }
}


// =========================================================
// NEW GROUP MODAL
// =========================================================

function openNewGroupModal() {

    selectedGroupMembers.clear();

    const modal =
        document.getElementById("newGroupModal");

    if (!modal) {
        console.error(
            "newGroupModal was not found in index.html"
        );

        return;
    }

    renderGroupContacts();

    updateSelectedGroupCount();

    modal.classList.add("show");
}


function closeNewGroupModal() {

    const modal =
        document.getElementById("newGroupModal");

    if (!modal) {
        return;
    }

    modal.classList.remove("show");

    selectedGroupMembers.clear();
}


// =========================================================
// GROUP CONTACT PICKER
// =========================================================

function renderGroupContacts() {

    const container =
        document.getElementById(
            "groupContactsList"
        );

    if (!container) {
        return;
    }

    if (!contacts.length) {

        container.innerHTML = `
            <div class="empty-state">
                No contacts available.
            </div>
        `;

        return;
    }

    container.innerHTML =
        contacts.map(contact => {

            const checked =
                selectedGroupMembers.has(
                    Number(contact.id)
                );

            const avatar =
                contact.avatar_url
                    ? `
                        <img
                            src="${escapeHtml(contact.avatar_url)}"
                            alt=""
                        >
                    `
                    : `
                        <span>
                            ${escapeHtml(
                                (contact.name || "U")
                                .charAt(0)
                                .toUpperCase()
                            )}
                        </span>
                    `;

            return `
                <label
                    class="group-contact-item"
                >

                    <input
                        type="checkbox"
                        value="${contact.id}"
                        ${checked ? "checked" : ""}
                        onchange="
                            toggleGroupMember(
                                ${contact.id},
                                this.checked
                            )
                        "
                    >

                    <div class="contact-avatar">
                        ${avatar}
                    </div>

                    <div class="contact-info">

                        <div class="contact-name">
                            ${escapeHtml(
                                contact.name || "Unknown"
                            )}
                        </div>

                        <div class="contact-email">
                            ${escapeHtml(
                                contact.email || ""
                            )}
                        </div>

                    </div>

                </label>
            `;

        }).join("");
}


// =========================================================
// SELECT GROUP MEMBER
// =========================================================

function toggleGroupMember(
    userId,
    checked
) {

    userId = Number(userId);

    if (checked) {
        selectedGroupMembers.add(userId);
    } else {
        selectedGroupMembers.delete(userId);
    }

    updateSelectedGroupCount();
}


function updateSelectedGroupCount() {

    const element =
        document.getElementById(
            "selectedGroupCount"
        );

    if (!element) {
        return;
    }

    const count =
        selectedGroupMembers.size;

    element.textContent =
        `${count} contact${count === 1 ? "" : "s"} selected`;
}


// =========================================================
// CREATE GROUP
// =========================================================

async function createGroup() {

    const nameInput =
        document.getElementById(
            "groupNameInput"
        );

    if (!nameInput) {
        return;
    }

    const groupName =
        nameInput.value.trim();

    if (!groupName) {

        alert(
            "Please enter a group name."
        );

        nameInput.focus();

        return;
    }

    if (selectedGroupMembers.size === 0) {

        alert(
            "Please select at least one contact."
        );

        return;
    }

    try {

        const data = await api(
            "/api/groups",
            {
                method: "POST",
                headers: {
                    "Content-Type":
                        "application/json"
                },
                body: JSON.stringify({

                    name: groupName,

                    member_ids:
                        Array.from(
                            selectedGroupMembers
                        )

                })
            }
        );

        if (!data.success) {

            throw new Error(
                data.message ||
                "Could not create group."
            );
        }

        alert(
            "Group created successfully!"
        );

        nameInput.value = "";

        closeNewGroupModal();

        if (
            typeof loadGroups ===
            "function"
        ) {
            await loadGroups();
        }

    } catch (error) {

        console.error(
            "createGroup:",
            error
        );

        alert(error.message);
    }
}


// =========================================================
// PROFILE MODAL
// =========================================================

function openProfileModal() {

    const modal =
        document.getElementById(
            "profileModal"
        );

    if (!modal) {
        console.error(
            "profileModal was not found."
        );

        return;
    }

    updateProfileUI();

    modal.classList.add("show");
}


function closeProfileModal() {

    const modal =
        document.getElementById(
            "profileModal"
        );

    if (!modal) {
        return;
    }

    modal.classList.remove("show");
}


// =========================================================
// PROFILE PHOTO
// =========================================================

async function uploadProfilePhoto(
    file
) {

    if (!file) {
        return;
    }

    const allowedTypes = [
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp"
    ];

    if (
        !allowedTypes.includes(
            file.type
        )
    ) {

        alert(
            "Please select a JPG, PNG, GIF or WEBP image."
        );

        return;
    }

    if (
        file.size >
        10 * 1024 * 1024
    ) {

        alert(
            "Profile photo must be smaller than 10MB."
        );

        return;
    }

    const formData =
        new FormData();

    formData.append(
        "photo",
        file
    );

    try {

        const response =
            await fetch(
                "/api/profile/photo",
                {
                    method: "POST",
                    body: formData,
                    credentials: "same-origin"
                }
            );

        const data =
            await response.json();

        if (!response.ok) {

            throw new Error(
                data.message ||
                "Upload failed."
            );
        }

        if (
            data.user
        ) {

            currentUser =
                data.user;

        } else if (
            data.avatar_url
        ) {

            currentUser.avatar_url =
                data.avatar_url;
        }

        updateProfileUI();

        await loadContacts();

        alert(
            "Profile photo updated!"
        );

    } catch (error) {

        console.error(
            "uploadProfilePhoto:",
            error
        );

        alert(
            error.message
        );
    }
}


// =========================================================
// FILE INPUT
// =========================================================

function chooseProfilePhoto() {

    const input =
        document.getElementById(
            "profilePhotoInput"
        );

    if (input) {
        input.click();
    }
}


// =========================================================
// LOGOUT
// =========================================================

async function logout() {

    try {

        await api(
            "/api/logout",
            {
                method: "POST"
            }
        );

        window.location.reload();

    } catch (error) {

        console.error(
            "logout:",
            error
        );

        alert(
            "Logout failed."
        );
    }
}


// =========================================================
// HTML ESCAPE
// =========================================================

function escapeHtml(value) {

    return String(value ?? "")
        .replace(
            /&/g,
            "&amp;"
        )
        .replace(
            /</g,
            "&lt;"
        )
        .replace(
            />/g,
            "&gt;"
        )
        .replace(
            /"/g,
            "&quot;"
        )
        .replace(
            /'/g,
            "&#039;"
        );
}


// =========================================================
// SEARCH CONTACTS
// =========================================================

function searchContacts(query) {

    const text =
        String(query || "")
        .toLowerCase()
        .trim();

    const items =
        document.querySelectorAll(
            "#contactsList .contact-item"
        );

    items.forEach(item => {

        const content =
            item.textContent
            .toLowerCase();

        item.style.display =
            !text ||
            content.includes(text)
                ? ""
                : "none";
    });
}


// =========================================================
// INITIALIZE
// =========================================================

document.addEventListener(
    "DOMContentLoaded",
    async () => {

        const loggedIn =
            await loadCurrentUser();

        if (!loggedIn) {
            return;
        }

        await loadContacts();

        // Profile photo input
        const photoInput =
            document.getElementById(
                "profilePhotoInput"
            );

        if (photoInput) {

            photoInput.addEventListener(
                "change",
                event => {

                    const file =
                        event.target.files[0];

                    if (file) {
                        uploadProfilePhoto(
                            file
                        );
                    }

                    event.target.value = "";
                }
            );
        }

        // Search
        const searchInput =
            document.getElementById(
                "contactSearch"
            );

        if (searchInput) {

            searchInput.addEventListener(
                "input",
                event => {

                    searchContacts(
                        event.target.value
                    );
                }
            );
        }

        // Close modals when clicking outside
        document.addEventListener(
            "click",
            event => {

                const groupModal =
                    document.getElementById(
                        "newGroupModal"
                    );

                const profileModal =
                    document.getElementById(
                        "profileModal"
                    );

                if (
                    event.target ===
                    groupModal
                ) {
                    closeNewGroupModal();
                }

                if (
                    event.target ===
                    profileModal
                ) {
                    closeProfileModal();
                }
            }
        );
    }
);
