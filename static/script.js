// ================= LOAD VOICES =================
speechSynthesis.onvoiceschanged = function () {
    console.log(speechSynthesis.getVoices());
};

// ================= GLOBAL STATES =================
let isVoiceMode = false;
let currentRec = null;
let isSpeaking = false;
let current_chat_id = null;
let ignoreAbort = false;

// ================= SEND MESSAGE (TEXT MODE) =================
function sendMessage() {
    let input = document.getElementById("msg");
    let msg = input.value;

    if (msg.trim() === "") return;

    let chatBox = document.getElementById("chat-box");

    // ✅ USER MESSAGE
    chatBox.innerHTML += `<div class="message user">${msg}</div>`;
    input.value = "";

    // ✅ SHOW TYPING DOTS
    chatBox.innerHTML += `
        <div class="message bot typing" id="typing">
            <span></span><span></span><span></span>
        </div>
    `;

    smoothScrollSmart();

    // ✅ API CALL
    fetch("/api/chat", {
        method: "POST",
        headers: {
            "Content-Type": "application/x-www-form-urlencoded"
        },
        body: "message=" + encodeURIComponent(msg) + "&chat_id=" + encodeURIComponent(current_chat_id)
    })
    .then(res => res.json())
    .then(data => {

        // ✅ REMOVE TYPING
        let typing = document.getElementById("typing");
        if (typing) typing.remove();

        if (data.action === "open_url") {
            window.open(data.url, "_blank");
            if (data.reply) {
                speakText(data.reply);
            }
            return;
        }

        let reply = data.reply;

        // ✅ BOT MESSAGE (STREAMING)
        let botDiv = document.createElement("div");
        botDiv.className = "message bot";
        chatBox.appendChild(botDiv);

        streamText(botDiv, reply);
        // ✅ force scroll to bottom
        let chatBox = document.getElementById("chat-box");
        chatBox.scrollTop = chatBox.scrollHeight;

        smoothScrollSmart();

        // 🔥 wait for Firebase title to save then refresh
        setTimeout(() => {
            loadChats();
        }, 3000);

    })
    .catch(err => {
        console.error("CHAT ERROR:", err);

        let typing = document.getElementById("typing");
        if (typing) typing.remove();

        chatBox.innerHTML += `<div class="message bot">Error occurred</div>`;
    });
}
// ================= TYPE EFFECT =================
function typeText(element, text) {
    let i = 0;
    element.innerHTML = "";

    let cursor = document.createElement("span");
    cursor.className = "cursor";
    cursor.innerText = "|";
    element.appendChild(cursor);

    function typing() {
        if (i < text.length) {
            cursor.insertAdjacentText("beforebegin", text.charAt(i));
            i++;
            setTimeout(typing, 20 + Math.random() * 20);
        } else {
            cursor.remove();

            // ✅ ADD BUTTONS HERE
            element.innerHTML += `
                <div class="msg-actions">
                    <button onclick="readText(this)">🔊 Read</button>
                    <button onclick="explainText(this)">📚 Explain</button>
                </div>
            `;
        }
    }

    typing();
}
// ================= VOICE MODE =================
function startVoiceMode() {
    if (isVoiceMode) return;

    isVoiceMode = true;
    speakText("Aura voice mode activated");

    // 🔥 WAIT until speaking ends
    setTimeout(() => {

    }, 1500);
}

function stopVoiceMode() {
    isVoiceMode = false;
    speechSynthesis.cancel();
    if (currentRec) currentRec.stop();
    speakText("Voice mode stopped");
}

// ================= VOICE LOOP =================
function voiceLoop() {
    if (!isVoiceMode || isSpeaking) return;

    let rec = new webkitSpeechRecognition();
    currentRec = rec;

    rec.lang = "en-IN";
    rec.continuous = false;
    rec.interimResults = false;
    rec.maxAlternatives = 3;

    console.log("🎤 Listening...");

    rec.onresult = function(e) {
        let msg = e.results[0][0].transcript.toLowerCase();
        console.log("User:", msg);

        // 🛑 STOP COMMAND
        if (
            msg.includes("stop") ||
            msg.includes("top") ||
            msg.includes("stap") ||
            msg.includes("stock")
        ) {
            console.log("🛑 FULL STOP");

            isVoiceMode = false;
            speechSynthesis.cancel();

            if (currentRec) currentRec.stop();

            speakText("Voice mode stopped");
            return;
        }

        rec.stop();
        processJarvis(msg);
    };

    // 🔥 FIXED ERROR HANDLER
    rec.onerror = function(e) {
        

        // ❌ ignore aborted (very important)
        if (e.error === "aborted"){
            ignoreAbort = true;
            return;
        }
        if (isVoiceMode) {
            setTimeout(() => voiceLoop(), 500);
        }
    };

    rec.onend = function() {
        if (ignoreAbort) {
            ignoreAbort = false;
            return;
        }

        if (!isSpeaking && isVoiceMode) {
            setTimeout(() => voiceLoop(), 800);
        }
    };
    try {
        rec.start();
    } catch (err) {
        console.log("Start error:", err);
    }
}

// ================= PROCESS VOICE =================
function processJarvis(msg) {
    fetch("/api/chat", {
        method: "POST",
        headers: {
            "Content-Type": "application/x-www-form-urlencoded"
        },
        body: "message=" + encodeURIComponent(msg) + "&chat_id=" + encodeURIComponent(current_chat_id)
    })
    .then(res => res.json())
    .then(data => {

        // 🔥 HANDLE OPEN COMMAND
        if (data.action === "open_url") {
            window.open(data.url, "_blank");
            if (data.reply) {
                speakText(data.reply);
            }
            return;
        }

        // 🔥 NORMAL AI RESPONSE
        speakText(data.reply);
    });
}
// ================= SINGLE MIC =================
function voice() {
    let rec = new webkitSpeechRecognition();

    rec.lang = "en-IN";
    rec.interimResults = false;
    rec.maxAlternatives = 1;

    showWave();

    // ✅ speak first, then start mic after delay
    speakText("I'm listening");

    setTimeout(() => {
        console.log("🎤 Listening...");
        rec.start();  // ✅ start AFTER speaking finishes
    }, 2000);  // wait 2 seconds

    rec.onresult = function(e) {
        let msg = e.results[0][0].transcript.toLowerCase();
        console.log("You said:", msg);
        sendVoiceMessage(msg);
    };

    rec.onerror = function(e) {
        console.error("Mic error:", e.error);
        if (e.error === "no-speech") {
            alert("Speak something boss 🎤");
        }
    };

    rec.onend = function () {
        hideWave();
    };
}

// ================= VOICE MESSAGE =================
function sendVoiceMessage(msg) {
    let chatBox = document.getElementById("chat-box");

    chatBox.innerHTML += `<div class="message user">${msg}</div>`;

    chatBox.innerHTML += `
        <div class="message bot typing" id="typing">
            <span></span><span></span><span></span>
        </div>
    `;

    smoothScrollSmart();

    fetch("/api/chat", {
        method: "POST",
        headers: {
            "Content-Type": "application/x-www-form-urlencoded"
        },
        body: "message=" + encodeURIComponent(msg) + "&chat_id=" + encodeURIComponent(current_chat_id)
    })
    .then(res => res.json())
    .then(data => {

        let typing = document.getElementById("typing");
        if (typing) typing.remove();

        let reply = data.reply;

        let botDiv = document.createElement("div");
        botDiv.className = "message bot";
        chatBox.appendChild(botDiv);

        typeText(botDiv, reply);

        speakText(reply);

        chatBox.scrollTop = chatBox.scrollHeight;
    });
}

// ================= ASK MORE =================
function askMore() {
    sendVoiceMessage("Explain in detail");
}

// ================= SPEAK =================
function getVoice() {
    let voices = speechSynthesis.getVoices();
    return voices.find(v => v.name.includes("Female")) || voices[0];
}

function speakText(text) {
    speechSynthesis.cancel();
    isSpeaking = true;

    // 🔥 VERY IMPORTANT (this was missing in your new code)
    if (currentRec) currentRec.stop();

    let speech = new SpeechSynthesisUtterance(text);
    speech.voice = getVoice();

    speech.onend = function () {
        isSpeaking = false;


        // 🔥 restart listening after speaking
        if (isVoiceMode) {
            setTimeout(() => voiceLoop(), 500);
        }
    };

    speechSynthesis.speak(speech);
}


// ================= HELPERS =================
function addMessage(text, sender) {
    let box = document.getElementById("chat-box");

    let div = document.createElement("div");
    div.className = "message " + sender;
    div.innerText = text;

    box.appendChild(div);
    smoothScrollSmart();
}

function showTyping() {
    let box = document.getElementById("chat-box");

    let typing = document.createElement("div");
    typing.className = "message bot typing";
    typing.id = "typing";

    typing.innerHTML = `<span></span><span></span><span></span>`;

    box.appendChild(typing);
}

function removeTyping() {
    let t = document.getElementById("typing");
    if (t) t.remove();
}

// ================= WAVE =================
function showWave() {
    const w = document.getElementById("wave");
    if (!w) return;
    w.style.display = "flex";
}

function hideWave() {
    const w = document.getElementById("wave");
    if (!w) return;
    w.style.display = "none";
}
// ================= ENTER KEY =================
document.getElementById("msg").addEventListener("keypress", function(e) {
    if (e.key === "Enter") {
        sendMessage();
    }
});

// ================= CHAT LIST =================
function newChat() {
    fetch("/new_chat", {
        method: "POST"
    })
    .then(res => res.json())
    .then(data => {
        current_chat_id = data.chat_id;
        document.getElementById("chat-box").innerHTML = "";
        loadChats();
    });
}

function loadChats() {
    fetch("/get_chats")
    .then(res => res.json())
    .then(chats => {
        let list = document.getElementById("chat-list");
        list.innerHTML = "";

        chats.forEach(chat => {
            let row = document.createElement("div");
            row.style.marginBottom = "4px";
            row.style.display = "flex";
            row.style.justifyContent = "space-between";
            row.style.alignItems = "center";
            row.style.padding = "4px 8px";
            row.style.borderRadius = "6px";
            row.style.fontSize = "14px"; 
            row.style.display = "flex";
            row.style.alignItems = "center";
            row.style.justifyContent = "space-between";
            

           // active highlight
           if (chat.id === current_chat_id) {
            row.style.background = "#3f5aa5";
            } else {
                row.style.background = "#2d3f6b";
            }
            

             // LEFT: title button
             let btn = document.createElement("button");
             btn.innerText = chat.title;
             btn.style.flex = "1";
             btn.style.background = "transparent";
             btn.style.border = "none";
             btn.style.color = "white";
             btn.style.textAlign = "left";
             btn.style.cursor = "pointer";
             btn.style.fontSize = "13px";
             btn.style.padding = "4px 6px";
             btn.style.whiteSpace = "nowrap";      // no line break
             btn.style.overflow = "hidden";        // hide extra text
             btn.style.flex = "1";
             btn.style.minWidth = "0";   // 🔥 VERY IMPORTANT

            btn.style.textOverflow = "ellipsis";  // show ...
            btn.style.maxWidth = "120px";         // 🔥 control width

            btn.onclick = () => {
                current_chat_id = chat.id;
                 loadChat(chat.id);
                 loadChats();
            };

            // RIGHT: icons container
            let actions = document.createElement("div");
            actions.style.display = "flex";
            actions.style.gap = "5px";
            actions.style.flexShrink = "0";  // 🔥 prevents icons from moving

           // ✏️ rename
           let editBtn = document.createElement("button");
           editBtn.innerHTML = '<i class="fas fa-pen"></i>';
           editBtn.onclick = () => renameChat(chat.id);

           // 🗑 delete
           let deleteBtn = document.createElement("button");
           deleteBtn.innerHTML = '<i class="fas fa-trash"></i>';

           deleteBtn.onclick = (e) => {
            e.stopPropagation();   // 🔥 prevents opening chat
            deleteChat(chat.id);
           };

           [editBtn, deleteBtn].forEach(btn => {
            btn.onmouseover = () => {
                btn.style.background = "#5a7cff";
                btn.style.transform = "scale(1.1)";
            };

            btn.onmouseout = () => {
                btn.style.background = "rgba(255,255,255,0.1)";
                btn.style.transform = "scale(1)";
            };
            btn.style.background = "rgba(255,255,255,0.1)";
            btn.style.border = "none";
            btn.style.borderRadius = "8px";
            btn.style.padding = "6px 8px";
            btn.style.cursor = "pointer";
            btn.style.transition = "0.2s";
            btn.style.backdropFilter = "blur(5px)";
           });
           // add buttons
           actions.appendChild(editBtn);
           actions.appendChild(deleteBtn);

          row.appendChild(btn);
          row.appendChild(actions);

          list.appendChild(row);
        });
    });
}

// ✅ FIX - add loadChats() to highlight active chat in sidebar
function loadChat(chatId) {
    current_chat_id = chatId;
    fetch(`/load_chat/${chatId}`)
    .then(res => res.json())
    .then(data => {
        let chatBox = document.getElementById("chat-box");
        chatBox.innerHTML = "";

        data.forEach(msg => {
            let div = document.createElement("div");
            div.className = "message " + (msg.role === "user" ? "user" : "bot");
            div.innerText = msg.content;
            chatBox.appendChild(div);
        });

        smoothScrollSmart();
        loadChats();  // ✅ ADD THIS - highlights active chat
    });
}

// ================= INIT =================
function smoothScrollSmart() {
    let box = document.getElementById("chat-box");

    let isNearBottom =
        box.scrollHeight - box.scrollTop - box.clientHeight < 100;

    if (isNearBottom) {
        box.scrollTo({
            top: box.scrollHeight,
            behavior: "smooth"
        });
    }
}

function streamText(element, text) {
    let words = text.split(" ");
    let i = 0;

    element.innerHTML = "<span class='cursor'>|</span>";

    function stream() {
        if (i < words.length) {

            element.innerHTML = element.innerHTML.replace('<span class="cursor">|</span>', '');
            element.innerHTML += words[i] + " <span class='cursor'>|</span>";

            i++;
            setTimeout(stream, 50);

        } else {

            element.innerHTML = element.innerHTML.replace('<span class="cursor">|</span>', '');

            // 🔥 THIS IS WHAT YOU ARE MISSING
            element.innerHTML += `
                <div class="msg-actions">
                    <button onclick="readText(this)">🔊 Read</button>
                    <button onclick="explainText(this)">📚 Explain</button>
                </div>
            `;
        }
    }

    stream();
}
function readText(btn) {
    let text = btn.parentElement.parentElement.innerText;
    speakText(text);   // you already have this
}

function explainText(btn) {
    let text = btn.parentElement.parentElement.innerText;
    sendVoiceMessage("Explain this in detail: " + text);
}
let renameId = null;

function renameChat(chatId) {
    renameId = chatId;

    document.getElementById("renameInput").value = ""; // clear old
    document.getElementById("renameModal").style.display = "flex";
}

function confirmRename() {
    let newTitle = document.getElementById("renameInput").value;

    if (!newTitle) return;

    fetch(`/rename_chat/${renameId}`, {
        method: "POST",
        headers: {
            "Content-Type": "application/x-www-form-urlencoded"
        },
        body: `title=${encodeURIComponent(newTitle)}`
    })
    .then(res => res.json())
    .then(() => {
        closeRename();
        loadChats(); // refresh sidebar
    });
}

function deleteChat(chatId) {
    deleteId = chatId;

    let modal = document.getElementById("deleteModal");
    if (modal) modal.style.display = "flex";
}

function confirmDelete() {
    if (!deleteId) return;

    let chatToDelete = deleteId;
    deleteId = null;  // ✅ clear immediately

    fetch(`/delete_chat/${chatToDelete}`, { method: "POST" })
    .then(res => res.json())
    .then(() => {
        closeDelete();

        // ✅ always clear if deleted chat was active
        if (chatToDelete === current_chat_id || current_chat_id === null) {
            current_chat_id = null;
            document.getElementById("chat-box").innerHTML = "";
        }

        // ✅ check what chats are left
        fetch("/get_chats")
        .then(res => res.json())
        .then(chats => {

            // filter out deleted one just in case
            let remaining = chats.filter(c => c.id !== chatToDelete);

            if (remaining.length === 0) {
                // ✅ no chats left → create one
                fetch("/new_chat", { method: "POST" })
                .then(res => res.json())
                .then(newData => {
                    current_chat_id = newData.chat_id;
                    loadChats();
                });
            } else {
                // ✅ chats exist → load first one
                current_chat_id = remaining[0].id;
                loadChat(remaining[0].id);
            }
        });
    })
    .catch(err => console.error("DELETE ERROR:", err));
}

function closeRename() {
    document.getElementById("renameModal").style.display = "none";
}

let deleteId = null;


function closeDelete() {
    deleteId = null; // ✅ reset
    document.getElementById("deleteModal").style.display = "none";
}


window.onload = function () {
    document.getElementById("msg").focus();

    // 🔥 HIDE WAVE ON START
    let w = document.getElementById("wave");
    if (w) w.style.display = "none";

    fetch("/get_chats")
    .then(res => res.json())
    .then(chats => {

        if (chats.length > 0) {
            let firstChat = chats[0];
            current_chat_id = firstChat.id;

            fetch(`/load_chat/${firstChat.id}`)
            .then(res => res.json())
            .then(data => {
                let chatBox = document.getElementById("chat-box");
                chatBox.innerHTML = "";

                data.forEach(msg => {
                    let div = document.createElement("div");
                    div.className = "message " + (msg.role === "user" ? "user" : "bot");
                    div.innerText = msg.content;
                    chatBox.appendChild(div);
                });

                smoothScrollSmart();
            });
        }

        loadChats();  // ✅ only once

    });
};

function deleteMemory(key) {
    fetch(`/delete_memory/${key}`, {
        method: "POST"
    })
    .then(() => {
        loadMemory();
    });
}

function loadMemory() {
    fetch("/get_memory")
    .then(res => res.json())
    .then(memory => {
        let box = document.getElementById("memory-box");
        if (!box) return;
        box.innerHTML = "";

        Object.entries(memory).forEach(([key, value]) => {
            box.innerHTML += `
                <div>${key}: ${value} 
                    <button onclick="deleteMemory('${key}')">❌</button>
                </div>
            `;
        });
    });
}