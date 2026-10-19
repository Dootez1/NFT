// Global Centayrus Toast Notification Helper
function showToast(message, type = 'info') {
    let toast = document.getElementById('toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'toast';
        toast.className = 'toast';
        document.body.appendChild(toast);
    }
    let icon = '';
    if (type === 'success') icon = '✓ ';
    if (type === 'error') icon = '✕ ';
    if (type === 'warning') icon = '⚠ ';
    toast.innerText = `${icon}${message}`;
    toast.style.display = 'block';
    requestAnimationFrame(() => toast.classList.add('show'));
    clearTimeout(window.__toastTimeout);
    window.__toastTimeout = setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.style.display = 'none', 220);
    }, 3500);
}

// Copy to Clipboard Helper
function copyText(text, successMsg = 'Скопировано в буфер обмена!') {
    navigator.clipboard.writeText(text).then(() => {
        showToast(successMsg, 'success');
    }).catch(() => {
        showToast('Не удалось скопировать', 'error');
    });
}

// Modal Helpers
function openModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.add('active');
}

function closeModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.remove('active');
}

// Dashboard Tabs Switcher
function switchTab(tabName) {
    document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    
    const targetContent = document.getElementById(`tab-${tabName}`);
    const targetNav = document.getElementById(`nav-${tabName}`);
    if (targetContent) targetContent.style.display = 'block';
    if (targetNav) targetNav.classList.add('active');
}

// Logout
async function doLogout() {
    try {
        await fetch('/api/auth/logout', { method: 'POST' });
        window.location.href = '/';
    } catch (e) {
        window.location.href = '/';
    }
}

// Demo Login
async function submitDemoLogin(e) {
    if (e) e.preventDefault();
    const userIdInput = document.getElementById('demo-user-id');
    const usernameInput = document.getElementById('demo-username');
    const userId = parseInt(userIdInput.value.trim());
    const username = usernameInput ? usernameInput.value.trim() : '';

    if (!userId || isNaN(userId)) {
        showToast('Пожалуйста, введите корректный Telegram ID!', 'error');
        return;
    }

    try {
        const res = await fetch('/api/auth/demo', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, username: username, first_name: username || 'Worker' })
        });
        const data = await res.json();
        if (data.ok) {
            showToast('Telegram ID успешно установлен!', 'success');
            closeModal('modal-switch-user');
            setTimeout(() => { window.location.reload(); }, 600);
        } else {
            showToast(data.detail || 'Ошибка авторизации', 'error');
        }
    } catch (err) {
        showToast('Ошибка сети: ' + err.message, 'error');
    }
}

// Connect Worker Bot
async function submitConnectBot(e) {
    if (e) e.preventDefault();
    const tokenInput = document.getElementById('bot-token-input');
    const token = tokenInput.value.trim();
    if (!token) {
        showToast('Введите токен бота от @BotFather!', 'warning');
        return;
    }

    const ownerIdInput = document.getElementById('bot-owner-id-input');
    const ownerId = ownerIdInput && ownerIdInput.value.trim() ? parseInt(ownerIdInput.value.trim()) : null;

    const btn = document.getElementById('btn-connect-bot');
    const originalText = btn.innerHTML;
    btn.innerHTML = '⏳ Проверка и запуск...';
    btn.disabled = true;

    try {
        const res = await fetch('/api/bots/connect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: token, user_id: ownerId })
        });
        const data = await res.json();
        if (data.ok) {
            showToast(data.message, 'success');
            closeModal('modal-add-bot');
            setTimeout(() => window.location.reload(), 1200);
        } else {
            showToast(data.detail || 'Не удалось подключить бота', 'error');
        }
    } catch (err) {
        showToast('Ошибка соединения: ' + err.message, 'error');
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

// Worker Bot Actions (restart, stop, delete)
async function botAction(action) {
    if (action === 'delete' && !confirm('Вы уверены, что хотите удалить этого бота из системы?')) {
        return;
    }

    try {
        const res = await fetch('/api/bots/action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: action })
        });
        const data = await res.json();
        if (data.ok) {
            showToast(data.message, 'success');
            setTimeout(() => window.location.reload(), 1000);
        } else {
            showToast(data.detail || 'Действие отклонено', 'error');
        }
    } catch (err) {
        showToast('Ошибка: ' + err.message, 'error');
    }
}

// Create Deal from Web Form
async function submitCreateDeal(e) {
    if (e) e.preventDefault();
    const nftName = document.getElementById('deal-nft-name').value.trim();
    const nftNumber = document.getElementById('deal-nft-number').value.trim();
    const starsAmount = parseInt(document.getElementById('deal-stars').value);
    const recipient = document.getElementById('deal-recipient').value.trim();
    const lang = document.getElementById('deal-lang').value;

    if (!nftName || !nftNumber || !starsAmount || starsAmount <= 0) {
        showToast('Заполните все обязательные поля корректно!', 'warning');
        return;
    }

    try {
        const res = await fetch('/api/deals/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                nft_name: nftName,
                nft_number: nftNumber,
                stars_amount: starsAmount,
                recipient: recipient,
                lang: lang
            })
        });
        const data = await res.json();
        if (data.ok) {
            showToast(`Сделка #${data.deal_id} успешно создана!`, 'success');
            document.getElementById('deal-result-box').style.display = 'block';
            document.getElementById('deal-result-link').value = data.deal_link;
        } else {
            showToast(data.detail || 'Не удалось создать сделку', 'error');
        }
    } catch (err) {
        showToast('Ошибка: ' + err.message, 'error');
    }
}

// Activate Promo Code
async function submitPromoCode(e) {
    if (e) e.preventDefault();
    const code = document.getElementById('promo-code-input').value.trim();
    if (!code) {
        showToast('Введите промокод!', 'warning');
        return;
    }

    try {
        const res = await fetch('/api/subscription/activate_code', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code: code })
        });
        const data = await res.json();
        if (data.ok) {
            showToast(data.message, 'success');
            setTimeout(() => window.location.reload(), 1500);
        } else {
            showToast(data.detail || 'Промокод недействителен', 'error');
        }
    } catch (err) {
        showToast('Ошибка: ' + err.message, 'error');
    }
}

// Order Subscription (CryptoBot, TON, Cards)
async function selectPlanPayment(plan, method) {
    try {
        const res = await fetch('/api/subscription/create_order', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ plan: plan, payment_method: method })
        });
        const data = await res.json();
        if (data.ok) {
            if (data.method === 'cryptobot' && data.pay_url) {
                window.open(data.pay_url, '_blank');
                showToast('Счёт в @CryptoBot открыт. Оплатите его и нажмите "Проверить оплату"', 'info');
                document.getElementById('check-payment-btn').style.display = 'inline-flex';
                document.getElementById('check-payment-btn').dataset.orderId = data.invoice_id;
                document.getElementById('check-payment-btn').dataset.plan = plan;
                document.getElementById('check-payment-btn').dataset.method = 'cryptobot';
            } else if (data.method === 'ton' && data.invoice) {
                openModal('modal-ton-payment');
                document.getElementById('ton-pay-amount').innerText = `${data.invoice.amount_ton} TON`;
                document.getElementById('ton-pay-address').innerText = data.invoice.address;
                document.getElementById('ton-pay-comment').innerText = data.invoice.comment;
                document.getElementById('ton-tonkeeper-btn').href = data.invoice.tonkeeper_url;
                
                document.getElementById('check-ton-btn').dataset.plan = plan;
            } else {
                showToast(data.message, 'info');
            }
        }
    } catch (err) {
        showToast('Ошибка создания заказа: ' + err.message, 'error');
    }
}

// Check TON Payment
async function checkTonPayment() {
    const btn = document.getElementById('check-ton-btn');
    const plan = btn.dataset.plan || 'standard';
    btn.innerText = '⏳ Проверка блокчейна...';
    btn.disabled = true;

    try {
        const res = await fetch('/api/subscription/check_order', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ plan: plan, payment_method: 'ton' })
        });
        const data = await res.json();
        if (data.paid) {
            showToast(data.message, 'success');
            setTimeout(() => window.location.reload(), 1500);
        } else {
            showToast(data.message, 'warning');
        }
    } catch (err) {
        showToast('Ошибка проверки: ' + err.message, 'error');
    } finally {
        btn.innerText = '🔄 Проверить оплату в TON';
        btn.disabled = false;
    }
}

// Admin: Grant Subscription
async function submitAdminGrant(e) {
    if (e) e.preventDefault();
    const uid = parseInt(document.getElementById('admin-grant-uid').value);
    const plan = document.getElementById('admin-grant-plan').value;
    const days = parseInt(document.getElementById('admin-grant-days').value);

    try {
        const res = await fetch('/api/admin/grant', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: uid, plan: plan, days: days })
        });
        const data = await res.json();
        if (data.ok) {
            showToast(data.message, 'success');
            setTimeout(() => window.location.reload(), 1200);
        } else {
            showToast(data.detail || 'Ошибка выдачи', 'error');
        }
    } catch (err) {
        showToast('Ошибка: ' + err.message, 'error');
    }
}

// Admin: Revoke Subscription
async function adminRevokeSub(userId) {
    if (!confirm(`Вы действительно хотите аннулировать подписку пользователя ${userId}?`)) return;

    try {
        const res = await fetch('/api/admin/revoke', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId })
        });
        const data = await res.json();
        if (data.ok) {
            showToast(data.message, 'success');
            setTimeout(() => window.location.reload(), 1000);
        } else {
            showToast(data.detail || 'Ошибка', 'error');
        }
    } catch (err) {
        showToast('Ошибка: ' + err.message, 'error');
    }
}
