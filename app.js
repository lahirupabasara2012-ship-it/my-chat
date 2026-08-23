```javascript
// =========================================================
// MYCHAT - APP.JS
// Complete frontend
// =========================================================

let currentUser = null;
let contacts = [];
let groups = [];

let appStarting = false;

let socket = null;

let selectedContactId = null;
let selectedGroupId = null;

let selectedGroupMembers = new Set();

let typingTimer = null;
let isTyping = false;


// =========================================================
// API
// =========================================================

async function api(url, options = {}) {

    const response = await fetch(url, {
        credentials: "same-origin",
        ...options
    });

    let data = {};

    try {
        data = await response.json();
    } catch (e) {}

    if (!response.ok) {
        throw new Error(
            data.message || `Request failed (${response.status})`
        );
    }

    return data;
}


// =========================================================
// ESCAPE HTML
// =========================================================

function escapeHtml(value) {

    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}


// =========================================================
// AUTH
// =========================================================

function showSignup() {

    document.getElementById("loginForm").style.display = "none";
    document.getElementById("signupForm").style.display = "block";
    setAuthMessage("");
}


function showLogin() {

    document.getElementById("signupForm").style.display = "none";
    document.getElementById("loginForm").style.display = "block";
    setAuthMessage("");
}


function setAuthMessage(message, error = true) {

    const element = document.getElementById("authMessage");

    if (!element) return;

    element.textContent = message || "";
    element.style.color = error ? "" : "#35c759";
}


async function login() {

    const email =
        document.getElementById("loginEmail").value.trim();

    const password =
        document.getElementById("loginPassword").value;

    if (!email || !password) {
        setAuthMessage("Enter email and password.");
        return;
    }

    const loginButton =
        document.querySelector("#loginForm button");

    if (loginButton) {
        loginButton.disabled = true;
        loginButton.textContent = "Logging in...";
    }

    setAuthMessage("Logging in...", false);

    try {

        console.log("LOGIN START");

        const data = await api("/api/login", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                email: email,
                password: password
            })
        });

        console.log("LOGIN RESPONSE:", data);

        if (!data || !data.success) {
            throw new Error(
                data?.message || "Login failed."
            );
        }

        if (!data.user) {
            throw new Error(
                "Login successful, but user data was not returned by server."
            );
        }

        currentUser = data.user;

        console.log("CURRENT USER:", currentUser);

        await startChatApp();

        console.log("CHAT APP STARTED");

    } catch (error) {

        console.error("LOGIN ERROR:", error);

        setAuthMessage(
            error?.message || "Login failed."
        );

    } finally {

        if (loginButton) {
            loginButton.disabled = false;
            loginButton.textContent = "➔ Login";
        }
    }
}

async function signup() {

    const name =
        document.getElementById("signupName").value.trim();

    const email =
        document.getElementById("signupEmail").value.trim();

    const password =
        document.getElementById("signupPassword").value;

    if (!name || !email || !password) {
        setAuthMessage("All fields are required.");
        return;
    }

    if (password.length < 6) {
        setAuthMessage("Password must be at least 6 characters.");
        return;
    }

    setAuthMessage("Creating account...", false);

    try {

        const data = await api("/api/signup", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                name,
                email,
                password
            })
        });

        if (!data.success) {
            throw new Error(data.message || "Signup failed.");
        }

        showLogin();

        document.getElementById("loginEmail").value = email;
        document.getElementById("loginPassword").value = password;

        setAuthMessage("Account created. Please login.", false);

    } catch (error) {

        console.error("SIGNUP:", error);
        setAuthMessage(error.message);
    }
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

        console.error("CURRENT USER:", error);
        return false;
    }
}


// =========================================================
// START APP
// =========================================================

async function startChatApp() {

    if (appStarting) {
        console.log("APP START ALREADY RUNNING");
        return;
    }

    if (!currentUser) {
        console.error("Cannot start app: currentUser is missing.");
        return;
    }

    appStarting = true;

    console.log("Starting MyChat app...");

    try {

        const authPage =
            document.getElementById("authPage");

        const chatApp =
            document.getElementById("chatApp");

        if (!authPage || !chatApp) {
            throw new Error(
                "Chat page elements not found."
            );
        }

        // Show chat app
        authPage.style.display = "none";
        chatApp.style.display = "flex";

        updateProfileUI();

        // Load contacts
        try {
            await loadContacts();
        } catch (error) {
            console.error(
                "LOAD CONTACTS DURING START:",
                error
            );
        }

        // Load groups
        try {
            await loadGroups();
        } catch (error) {
            console.error(
                "LOAD GROUPS DURING START:",
                error
            );
        }

        // Connect socket
        connectSocket();

        console.log("MyChat app ready.");

    } catch (error) {

        console.error(
            "START CHAT APP ERROR:",
            error
        );

        // If startup failed, show login page again
        const authPage =
            document.getElementById("authPage");

        const chatApp =
            document.getElementById("chatApp");

        if (authPage) {
            authPage.style.display = "flex";
        }

        if (chatApp) {
            chatApp.style.display = "none";
        }

        setAuthMessage(
            error?.message ||
            "Could not start MyChat."
        );

    } finally {

        appStarting = false;
    }
}

// =========================================================
// PROFILE UI
// =========================================================

function updateProfileUI() {

    if (!currentUser) return;

    const name =
        currentUser.name || "User";

    const currentName =
        document.getElementById("currentUserName");

    if (currentName) {
        currentName.textContent = name;
    }

    const profileName =
        document.getElementById("profileNameInput");

    if (profileName) {
        profileName.value = name;
    }

    const profileEmail =
        document.getElementById("profileEmailInput");

    if (profileEmail) {
        profileEmail.value =
            currentUser.email || "";
    }

    const avatar =
        document.getElementById("profileAvatar");

    if (avatar) {

        if (currentUser.avatar_url) {

            avatar.innerHTML = `
                <img
                    src="${escapeHtml(currentUser.avatar_url)}"
                    alt="Profile"
                >
            `;

        } else {

            avatar.textContent =
                name.charAt(0).toUpperCase();
        }
    }

    updateChatAvatar();
}


function updateChatAvatar() {

    if (!selectedContactId) return;

    const contact =
        contacts.find(
            c => Number(c.id) === Number(selectedContactId)
        );

    if (!contact) return;

    setAvatar(
        document.getElementById("chatAvatar"),
        contact
    );
}


function setAvatar(element, user) {

    if (!element || !user) return;

    if (user.avatar_url) {

        element.innerHTML = `
            <img
                src="${escapeHtml(user.avatar_url)}"
                alt=""
            >
        `;

    } else {

        element.textContent =
            (user.name || "U")
            .charAt(0)
            .toUpperCase();
    }
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

        if (selectedContactId) {
            updateChatAvatar();
        }

    } catch (error) {

        console.error("CONTACTS:", error);

        const container =
            document.getElementById("contacts");

        if (container) {
            container.innerHTML = `
                <div class="empty-state">
                    Unable to load contacts.
                </div>
            `;
        }
    }
}


function renderContacts() {

    const container =
        document.getElementById("contacts");

    if (!container) return;

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

            const active =
                Number(selectedContactId) === Number(contact.id)
                    ? " active"
                    : "";

            const unread =
                Number(contact.unread || 0);

            return `
                <div
                    class="contact-item${active}"
                    data-contact-id="${contact.id}"
                    onclick="openPrivateChat(${contact.id})"
                >

                    <div class="contact-avatar">
                        ${avatar}
                    </div>

                    <div class="contact-info">

                        <div class="contact-name">
                            ${escapeHtml(contact.name || "Unknown")}

                            ${
                                unread > 0
                                ? `<span class="unread-badge">${unread}</span>`
                                : ""
                            }
                        </div>

                        <div class="contact-email">
                            ${escapeHtml(contact.last_message || contact.email || "")}
                        </div>

                    </div>

                    ${
                        contact.online
                        ? `<span class="online-dot"></span>`
                        : ""
                    }

                </div>
            `;

        }).join("");
}


// =========================================================
// OPEN PRIVATE CHAT
// =========================================================

async function openPrivateChat(userId) {

    const contact =
        contacts.find(
            c => Number(c.id) === Number(userId)
        );

    if (!contact) return;

    selectedContactId = Number(userId);
    selectedGroupId = null;

    renderContacts();
    renderGroups();

    document.getElementById("chatName").textContent =
        contact.name || "User";

    document.getElementById("chatStatus").textContent =
        contact.online ? "Online" : "Offline";

    setAvatar(
        document.getElementById("chatAvatar"),
        contact
    );

    enableMessageInput(true);

    await loadMessages(selectedContactId);

    markRead(selectedContactId);
}


// =========================================================
// LOAD PRIVATE MESSAGES
// =========================================================

async function loadMessages(contactId) {

    const container =
        document.getElementById("messages");

    if (!container) return;

    container.innerHTML = `
        <div class="empty-chat">
            Loading messages...
        </div>
    `;

    try {

        const data =
            await api(`/api/messages/${contactId}`);

        const messages =
            Array.isArray(data.messages)
                ? data.messages
                : [];

        renderPrivateMessages(messages);

    } catch (error) {

        console.error("LOAD MESSAGES:", error);

        container.innerHTML = `
            <div class="empty-chat">
                Unable to load messages.
            </div>
        `;
    }
}


// =========================================================
// MESSAGE RENDER
// =========================================================

function renderPrivateMessages(messages) {

    const container =
        document.getElementById("messages");

    if (!messages.length) {

        container.innerHTML = `
            <div class="empty-chat">
                No messages yet. Say hello 👋
            </div>
        `;

        return;
    }

    container.innerHTML =
        messages.map(renderMessage).join("");

    scrollMessagesToBottom();
}


function renderMessage(message) {

    const mine =
        Number(message.sender_id) === Number(currentUser.id);

    const time =
        formatTime(message.created_at);

    let content = "";

    if (message.message_type === "image") {

        content = `
            <a
                href="${escapeHtml(message.file_url)}"
                target="_blank"
                rel="noopener"
            >
                <img
                    class="chat-image"
                    src="${escapeHtml(message.file_url)}"
                    alt="${escapeHtml(message.file_name || "Image")}"
                >
            </a>
        `;

    } else if (message.message_type === "video") {

        content = `
            <video
                class="chat-video"
                controls
                src="${escapeHtml(message.file_url)}"
            ></video>
        `;

    } else if (message.message_type === "file") {

        content = `
            <a
                class="chat-file"
                href="${escapeHtml(message.file_url)}"
                target="_blank"
                rel="noopener"
            >
                📎 ${escapeHtml(message.file_name || "File")}
            </a>
        `;

    } else {

        content =
            escapeHtml(message.message)
            .replace(/\n/g, "<br>");
    }

    let status = "";

    if (mine) {

        if (Number(message.is_read) === 1) {
            status = `<span class="message-status seen">✓✓</span>`;
        } else {
            status = `<span class="message-status">✓</span>`;
        }
    }

    return `
        <div
            class="message-row ${mine ? "mine" : "theirs"}"
            data-message-id="${message.id}"
        >

            <div class="message-bubble">

                <div class="message-content">
                    ${content}
                </div>

                <div class="message-meta">
                    <span>${escapeHtml(time)}</span>
                    ${status}
                </div>

            </div>

        </div>
    `;
}


function appendMessage(message) {

    if (!selectedContactId) return;

    const sender =
        Number(message.sender_id);

    const receiver =
        Number(message.receiver_id);

    const myId =
        Number(currentUser.id);

    if (
        sender !== myId &&
        receiver !== myId
    ) {
        return;
    }

    if (
        sender !== Number(selectedContactId) &&
        receiver !== Number(selectedContactId)
    ) {
        return;
    }

    const container =
        document.getElementById("messages");

    const empty =
        container.querySelector(".empty-chat");

    if (empty) {
        container.innerHTML = "";
    }

    if (
        container.querySelector(
            `[data-message-id="${message.id}"]`
        )
    ) {
        return;
    }

    container.insertAdjacentHTML(
        "beforeend",
        renderMessage(message)
    );

    scrollMessagesToBottom();
}


// =========================================================
// GROUPS
// =========================================================

async function loadGroups() {

    try {

        const data =
            await api("/api/groups");

        groups =
            Array.isArray(data.groups)
                ? data.groups
                : [];

        renderGroups();

    } catch (error) {

        console.error("GROUPS:", error);
    }
}


function renderGroups() {

    const container =
        document.getElementById("groups");

    if (!container) return;

    if (!groups.length) {
        container.innerHTML = "";
        return;
    }

    container.innerHTML =
        groups.map(group => {

            const active =
                Number(selectedGroupId) === Number(group.id)
                    ? " active"
                    : "";

            return `
                <div
                    class="contact-item group-item${active}"
                    onclick="openGroupChat(${group.id})"
                >

                    <div class="contact-avatar">
                        👥
                    </div>

                    <div class="contact-info">

                        <div class="contact-name">
                            ${escapeHtml(group.name)}
                        </div>

                        <div class="contact-email">
                            ${Number(group.member_count || 0)} members
                        </div>

                    </div>

                </div>
            `;

        }).join("");
}


async function openGroupChat(groupId) {

    const group =
        groups.find(
            g => Number(g.id) === Number(groupId)
        );

    if (!group) return;

    selectedGroupId = Number(groupId);
    selectedContactId = null;

    renderGroups();
    renderContacts();

    document.getElementById("chatName").textContent =
        group.name;

    document.getElementById("chatStatus").textContent =
        `${group.member_count || 0} members`;

    document.getElementById("chatAvatar").textContent =
        "👥";

    enableMessageInput(true);

    await loadGroupMessages(groupId);
}


async function loadGroupMessages(groupId) {

    const container =
        document.getElementById("messages");

    container.innerHTML = `
        <div class="empty-chat">
            Loading group messages...
        </div>
    `;

    try {

        const data =
            await api(`/api/groups/${groupId}/messages`);

        const messages =
            Array.isArray(data.messages)
                ? data.messages
                : [];

        if (!messages.length) {

            container.innerHTML = `
                <div class="empty-chat">
                    No group messages yet.
                </div>
            `;

            return;
        }

        container.innerHTML =
            messages.map(message => {

                const mine =
                    Number(message.sender_id) === Number(currentUser.id);

                return `
                    <div class="message-row ${mine ? "mine" : "theirs"}">

                        <div class="message-bubble">

                            ${
                                !mine
                                ? `<div class="group-sender">${escapeHtml(message.sender_name)}</div>`
                                : ""
                            }

                            <div class="message-content">
                                ${escapeHtml(message.message).replace(/\n/g, "<br>")}
                            </div>

                            <div class="message-meta">
                                ${escapeHtml(formatTime(message.created_at))}
                            </div>

                        </div>

                    </div>
                `;

            }).join("");

        scrollMessagesToBottom();

    } catch (error) {

        console.error("GROUP MESSAGES:", error);

        container.innerHTML = `
            <div class="empty-chat">
                Unable to load group messages.
            </div>
        `;
    }
}


// =========================================================
// SEND MESSAGE
// =========================================================

function sendCurrentMessage() {

    const input =
        document.getElementById("messageInput");

    const message =
        input.value.trim();

    if (!message) return;

    if (!socket || !socket.connected) {

        showNotification(
            "Connecting to chat server..."
        );

        return;
    }

    if (selectedGroupId) {

        socket.emit(
            "send_group_message",
            {
                group_id: selectedGroupId,
                message
            }
        );

    } else if (selectedContactId) {

        socket.emit(
            "send_message",
            {
                receiver_id: selectedContactId,
                message
            }
        );

    } else {

        return;
    }

    input.value = "";

    stopTyping();
}


function enableMessageInput(enabled) {

    document.getElementById("messageInput").disabled =
        !enabled;

    document.getElementById("sendBtn").disabled =
        !enabled;

    document.getElementById("fileBtn").disabled =
        !enabled;

    if (enabled) {
        document.getElementById("messageInput").focus();
    }
}


// =========================================================
// SOCKET.IO
// =========================================================

function connectSocket() {

    if (socket) {

        try {
            socket.disconnect();
        } catch (e) {}
    }

    socket = io({
        transports: ["polling", "websocket"],
        reconnection: true,
        reconnectionAttempts: Infinity,
        reconnectionDelay: 1000
    });


    socket.on("connect", () => {

        console.log(
            "Socket connected:",
            socket.id
        );
    });


    socket.on("disconnect", reason => {

        console.log(
            "Socket disconnected:",
            reason
        );
    });


    socket.on("connect_error", error => {

        console.error(
            "Socket connection error:",
            error
        );
    });


    socket.on("online_users", data => {

        const ids =
            Array.isArray(data?.users)
                ? data.users
                : [];

        contacts.forEach(contact => {

            contact.online =
                ids.includes(Number(contact.id));
        });

        renderContacts();
        updateChatStatus();

    });


    socket.on("user_status", data => {

        if (!data) return;

        const userId =
            Number(data.user_id);

        const contact =
            contacts.find(
                c => Number(c.id) === userId
            );

        if (contact) {

            contact.online =
                Boolean(data.online);

            renderContacts();
        }

        if (
            selectedContactId === userId
        ) {
            updateChatStatus();
        }
    });


    socket.on("new_message", message => {

        if (!message) return;

        appendMessage(message);

        const senderId =
            Number(message.sender_id);

        const myId =
            Number(currentUser.id);

        if (
            senderId !== myId
            &&
            selectedContactId === senderId
        ) {

            socket.emit(
                "message_delivered_ack",
                {
                    message_id: message.id,
                    sender_id: senderId
                }
            );

            markRead(senderId);
        }

        if (senderId !== myId) {
            loadContacts();
        }
    });


    socket.on("message_sent", message => {

        if (!message) return;

        appendMessage(message);
    });


    socket.on("message_delivered", data => {

        if (!data) return;

        const element =
            document.querySelector(
                `[data-message-id="${data.message_id}"]`
            );

        if (!element) return;

        const status =
            element.querySelector(".message-status");

        if (status) {
            status.textContent = "✓✓";
        }
    });


    socket.on("messages_read", data => {

        if (!data) return;

        const contactId =
            Number(data.contact_id);

        if (
            selectedContactId !== contactId
        ) {
            return;
        }

        document
            .querySelectorAll(".message-status")
            .forEach(status => {

                status.textContent = "✓✓";
                status.classList.add("seen");

            });

        loadContacts();
    });


    socket.on("user_typing", data => {

        if (!data) return;

        if (
            Number(data.user_id) !==
            Number(selectedContactId)
        ) {
            return;
        }

        const indicator =
            document.getElementById("typingIndicator");

        const text =
            document.getElementById("typingText");

        if (data.typing) {

            text.textContent = "Typing...";
            indicator.style.display = "flex";

        } else {

            indicator.style.display = "none";
        }
    });


    socket.on("group_message", message => {

        if (!message) return;

        if (
            selectedGroupId !==
            Number(message.group_id)
        ) {
            loadGroups();
            return;
        }

        const container =
            document.getElementById("messages");

        const empty =
            container.querySelector(".empty-chat");

        if (empty) {
            container.innerHTML = "";
        }

        const mine =
            Number(message.sender_id) ===
            Number(currentUser.id);

        container.insertAdjacentHTML(
            "beforeend",
            `
            <div class="message-row ${mine ? "mine" : "theirs"}">

                <div class="message-bubble">

                    ${
                        !mine
                        ? `<div class="group-sender">${escapeHtml(message.sender_name)}</div>`
                        : ""
                    }

                    <div class="message-content">
                        ${escapeHtml(message.message).replace(/\n/g, "<br>")}
                    </div>

                    <div class="message-meta">
                        ${escapeHtml(formatTime(message.created_at))}
                    </div>

                </div>

            </div>
            `
        );

        scrollMessagesToBottom();
        loadGroups();
    });


    socket.on("message_error", data => {

        showNotification(
            data?.message || "Message could not be sent."
        );
    });
}


// =========================================================
// TYPING
// =========================================================

function handleTyping() {

    if (
        !socket ||
        !socket.connected ||
        !selectedContactId
    ) {
        return;
    }

    if (!isTyping) {

        isTyping = true;

        socket.emit(
            "typing",
            {
                receiver_id: selectedContactId,
                typing: true
            }
        );
    }

    clearTimeout(typingTimer);

    typingTimer = setTimeout(
        stopTyping,
        1200
    );
}


function stopTyping() {

    clearTimeout(typingTimer);

    if (
        isTyping &&
        socket &&
        socket.connected &&
        selectedContactId
    ) {

        socket.emit(
            "typing",
            {
                receiver_id: selectedContactId,
                typing: false
            }
        );
    }

    isTyping = false;
}


// =========================================================
// READ
// =========================================================

async function markRead(contactId) {

    try {

        await api(
            `/api/messages/${contactId}/read`,
            {
                method: "POST"
            }
        );

        if (socket && socket.connected) {

            socket.emit(
                "mark_read",
                {
                    contact_id: contactId
                }
            );
        }

        loadContacts();

    } catch (error) {

        console.error("MARK READ:", error);
    }
}


// =========================================================
// FILE UPLOAD
// =========================================================

async function uploadChatFile(file) {

    if (!file || !selectedContactId) {
        return;
    }

    const formData =
        new FormData();

    formData.append(
        "file",
        file
    );

    formData.append(
        "receiver_id",
        selectedContactId
    );

    showNotification("Uploading file...");

    try {

        const data =
            await fetch(
                "/api/upload",
                {
                    method: "POST",
                    credentials: "same-origin",
                    body: formData
                }
            ).then(async response => {

                const result =
                    await response.json();

                if (!response.ok) {
                    throw new Error(
                        result.message ||
                        "Upload failed."
                    );
                }

                return result;
            });

        if (data.success && data.message) {

            appendMessage(data.message);
            showNotification("File sent.");
        }

    } catch (error) {

        console.error("FILE UPLOAD:", error);

        showNotification(
            error.message || "File upload failed."
        );
    }
}


// =========================================================
// ADD CONTACT
// =========================================================

async function addContact(email) {

    const data =
        await api(
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

    await loadContacts();

    return data;
}


// =========================================================
// GROUP MODAL
// =========================================================

function openNewGroupModal() {

    selectedGroupMembers.clear();

    document.getElementById("groupNameInput").value = "";
    document.getElementById("groupMessage").textContent = "";

    renderGroupContacts();
    updateSelectedGroupCount();

    document
        .getElementById("groupModal")
        .classList.add("show");
}


function closeNewGroupModal() {

    document
        .getElementById("groupModal")
        .classList.remove("show");

    selectedGroupMembers.clear();
}


function renderGroupContacts() {

    const container =
        document.getElementById("groupContactPicker");

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
                    ? `<img src="${escapeHtml(contact.avatar_url)}" alt="">`
                    : `<span>${escapeHtml(
                        (contact.name || "U")
                        .charAt(0)
                        .toUpperCase()
                    )}</span>`;

            return `
                <label class="group-contact-item">

                    <input
                        type="checkbox"
                        ${checked ? "checked" : ""}
                        onchange="
                            toggleGroupMember(
                                ${Number(contact.id)},
                                this.checked
                            )
                        "
                    >

                    <div class="contact-avatar">
                        ${avatar}
                    </div>

                    <div class="contact-info">

                        <div class="contact-name">
                            ${escapeHtml(contact.name)}
                        </div>

                        <div class="contact-email">
                            ${escapeHtml(contact.email)}
                        </div>

                    </div>

                </label>
            `;

        }).join("");
}


function toggleGroupMember(userId, checked) {

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
        document.getElementById("groupSelectedCount");

    const count =
        selectedGroupMembers.size;

    element.textContent =
        `${count} contact${count === 1 ? "" : "s"} selected`;
}


async function createGroup() {

    const name =
        document.getElementById("groupNameInput")
        .value
        .trim();

    if (!name) {

        document.getElementById("groupMessage")
            .textContent =
            "Enter a group name.";

        return;
    }

    if (!selectedGroupMembers.size) {

        document.getElementById("groupMessage")
            .textContent =
            "Select at least one contact.";

        return;
    }

    try {

        const data =
            await api(
                "/api/groups",
                {
                    method: "POST",
                    headers: {
                        "Content-Type":
                            "application/json"
                    },
                    body: JSON.stringify({
                        name,
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

        closeNewGroupModal();

        await loadGroups();

        showNotification(
            "Group created successfully."
        );

    } catch (error) {

        console.error("CREATE GROUP:", error);

        document.getElementById("groupMessage")
            .textContent =
            error.message;
    }
}


// =========================================================
// PROFILE
// =========================================================

function openProfileModal() {

    updateProfileUI();

    document
        .getElementById("profileModal")
        .classList.add("show");
}


function closeProfileModal() {

    document
        .getElementById("profileModal")
        .classList.remove("show");
}


async function saveProfile() {

    const name =
        document.getElementById("profileNameInput")
        .value
        .trim();

    if (!name) {

        document.getElementById("profileMessage")
            .textContent =
            "Name is required.";

        return;
    }

    try {

        const data =
            await api(
                "/api/profile",
                {
                    method: "PUT",
                    headers: {
                        "Content-Type":
                            "application/json"
                    },
                    body: JSON.stringify({
                        name
                    })
                }
            );

        currentUser = {
            ...currentUser,
            ...data.user
        };

        updateProfileUI();
        await loadContacts();

        document.getElementById("profileMessage")
            .textContent =
            "Profile updated.";

    } catch (error) {

        document.getElementById("profileMessage")
            .textContent =
            error.message;
    }
}


async function uploadProfilePhoto(file) {

    if (!file) return;

    if (![
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp"
    ].includes(file.type)) {

        showNotification(
            "Please select a JPG, PNG, GIF or WEBP image."
        );

        return;
    }

    if (file.size > 10 * 1024 * 1024) {

        showNotification(
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
                    credentials: "same-origin",
                    body: formData
                }
            );

        const data =
            await response.json();

        if (!response.ok) {
            throw new Error(
                data.message ||
                "Photo upload failed."
            );
        }

        currentUser = {
            ...currentUser,
            ...data.user
        };

        updateProfileUI();

        await loadContacts();

        showNotification(
            "Profile photo updated."
        );

    } catch (error) {

        console.error(
            "PROFILE PHOTO:",
            error
        );

        showNotification(
            error.message
        );
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

    } catch (error) {

        console.error("LOGOUT:", error);
    }

    if (socket) {
        socket.disconnect();
    }

    window.location.reload();
}


// =========================================================
// SEARCH
// =========================================================

function searchContacts(query) {

    const text =
        String(query || "")
        .toLowerCase()
        .trim();

    document
        .querySelectorAll(
            "#contacts .contact-item"
        )
        .forEach(item => {

            item.style.display =
                !text ||
                item.textContent
                    .toLowerCase()
                    .includes(text)
                    ? ""
                    : "none";
        });
}


// =========================================================
// HELPERS
// =========================================================

function formatTime(value) {

    if (!value) return "";

    const date =
        new Date(
            String(value).replace(" ", "T")
        );

    if (Number.isNaN(date.getTime())) {
        return "";
    }

    return date.toLocaleTimeString(
        [],
        {
            hour: "2-digit",
            minute: "2-digit"
        }
    );
}


function scrollMessagesToBottom() {

    const container =
        document.getElementById("messages");

    if (!container) return;

    requestAnimationFrame(() => {

        container.scrollTop =
            container.scrollHeight;

    });
}


function updateChatStatus() {

    if (!selectedContactId) return;

    const contact =
        contacts.find(
            c => Number(c.id) === Number(selectedContactId)
        );

    if (!contact) return;

    document.getElementById("chatStatus")
        .textContent =
        contact.online ? "Online" : "Offline";
}


function showNotification(message) {

    const notification =
        document.getElementById("notification");

    const text =
        document.getElementById("notificationText");

    if (!notification || !text) return;

    text.textContent = message;

    notification.style.display = "block";

    clearTimeout(
        window.myChatNotificationTimer
    );

    window.myChatNotificationTimer =
        setTimeout(() => {

            notification.style.display = "none";

        }, 2500);
}


// =========================================================
// EVENTS
// =========================================================

document.addEventListener(
    "DOMContentLoaded",
    async () => {

        // ---------------------------------------------
        // Check login
        // ---------------------------------------------

        try {

            const loggedIn =
                await loadCurrentUser();

            console.log(
                "Existing session:",
                loggedIn
            );

            if (loggedIn && currentUser) {
                await startChatApp();
            }

        } catch (error) {

            console.error(
                "SESSION CHECK ERROR:",
                error
            );

        }


        // ---------------------------------------------
        // Send
        // ---------------------------------------------

        document
            .getElementById("sendBtn")
            .addEventListener(
                "click",
                sendCurrentMessage
            );


        // ---------------------------------------------
        // Enter key
        // ---------------------------------------------

        document
            .getElementById("messageInput")
            .addEventListener(
                "keydown",
                event => {

                    if (
                        event.key === "Enter" &&
                        !event.shiftKey
                    ) {

                        event.preventDefault();
                        sendCurrentMessage();
                    }
                }
            );


        // ---------------------------------------------
        // Typing
        // ---------------------------------------------

        document
            .getElementById("messageInput")
            .addEventListener(
                "input",
                handleTyping
            );


        // ---------------------------------------------
        // File
        // ---------------------------------------------

        document
            .getElementById("fileBtn")
            .addEventListener(
                "click",
                () => {
                    document
                        .getElementById("fileInput")
                        .click();
                }
            );


        document
            .getElementById("fileInput")
            .addEventListener(
                "change",
                event => {

                    const file =
                        event.target.files[0];

                    if (file) {
                        uploadChatFile(file);
                    }

                    event.target.value = "";
                }
            );


        // ---------------------------------------------
        // Search
        // ---------------------------------------------

        document
            .getElementById("searchInput")
            .addEventListener(
                "input",
                event => {
                    searchContacts(
                        event.target.value
                    );
                }
            );


        // ---------------------------------------------
        // Add contact
        // ---------------------------------------------

        document
            .getElementById("addContactBtn")
            .addEventListener(
                "click",
                () => {

                    document
                        .getElementById("contactModal")
                        .classList.add("show");

                    document
                        .getElementById("emailInput")
                        .focus();
                }
            );


        document
            .getElementById("closeModal")
            .addEventListener(
                "click",
                () => {

                    document
                        .getElementById("contactModal")
                        .classList.remove("show");
                }
            );


        document
            .getElementById("confirmContact")
            .addEventListener(
                "click",
                async () => {

                    const email =
                        document
                            .getElementById("emailInput")
                            .value
                            .trim();

                    if (!email) return;

                    const message =
                        document
                            .getElementById("contactMessage");

                    try {

                        await addContact(email);

                        message.textContent =
                            "Contact added successfully.";

                        document
                            .getElementById("emailInput")
                            .value = "";

                    } catch (error) {

                        message.textContent =
                            error.message;
                    }
                }
            );


        // ---------------------------------------------
        // Profile
        // ---------------------------------------------

        document
            .getElementById("profileBtn")
            .addEventListener(
                "click",
                openProfileModal
            );


        document
            .getElementById("closeProfileModal")
            .addEventListener(
                "click",
                closeProfileModal
            );


        document
            .getElementById("saveProfileBtn")
            .addEventListener(
                "click",
                saveProfile
            );


        document
            .getElementById("profilePhotoInput")
            .addEventListener(
                "change",
                event => {

                    const file =
                        event.target.files[0];

                    if (file) {
                        uploadProfilePhoto(file);
                    }

                    event.target.value = "";
                }
            );


        // ---------------------------------------------
        // Groups
        // ---------------------------------------------

        document
            .getElementById("newGroupBtn")
            .addEventListener(
                "click",
                openNewGroupModal
            );


        document
            .getElementById("closeGroupModal")
            .addEventListener(
                "click",
                closeNewGroupModal
            );


        document
            .getElementById("createGroupBtn")
            .addEventListener(
                "click",
                createGroup
            );


        // ---------------------------------------------
        // Close modal outside
        // ---------------------------------------------

        document.addEventListener(
            "click",
            event => {

                const contactModal =
                    document.getElementById("contactModal");

                const profileModal =
                    document.getElementById("profileModal");

                const groupModal =
                    document.getElementById("groupModal");

                if (event.target === contactModal) {
                    contactModal.classList.remove("show");
                }

                if (event.target === profileModal) {
                    profileModal.classList.remove("show");
                }

                if (event.target === groupModal) {
                    groupModal.classList.remove("show");
                }
            }
        );

    }
);
```
