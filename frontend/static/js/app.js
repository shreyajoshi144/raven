// Raven Platform - Frontend Application

// API Configuration
const API_BASE_URL = '/api/v1';

// State Management
let currentUser = null;
let authToken = null;
let currentLocation = null;

// DOM Elements
const navMenu = document.getElementById('navMenu');
const navAuth = document.getElementById('navAuth');
const sections = document.querySelectorAll('.section');
const navLinks = document.querySelectorAll('.nav-link');

// Initialize App
document.addEventListener('DOMContentLoaded', () => {
    initializeApp();
});

function initializeApp() {
    // Check for existing auth token
    authToken = localStorage.getItem('raven_token');
    if (authToken) {
        fetchCurrentUser();
    } else {
        showLoginModal();
    }
    
    // Setup event listeners
    setupEventListeners();
    
    // Get user location
    getCurrentLocation();
}

// API Helper Functions
async function apiRequest(endpoint, options = {}) {
    const url = `${API_BASE_URL}${endpoint}`;
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };
    
    if (authToken) {
        headers['Authorization'] = `Bearer ${authToken}`;
    }
    
    try {
        const response = await fetch(url, {
            ...options,
            headers
        });
        
        if (response.status === 401) {
            logout();
            return null;
        }
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Request failed');
        }
        
        return await response.json();
    } catch (error) {
        console.error('API Error:', error);
        showToast(error.message, 'error');
        return null;
    }
}

// Authentication Functions
async function fetchCurrentUser() {
    const user = await apiRequest('/auth/me');
    if (user) {
        currentUser = user;
        updateUIForLoggedInUser();
        loadDashboardData();
    }
}

async function login(email, password) {
    const formData = new FormData();
    formData.append('username', email);
    formData.append('password', password);
    
    const response = await fetch(`${API_BASE_URL}/auth/login`, {
        method: 'POST',
        body: formData
    });
    
    if (response.ok) {
        const data = await response.json();
        authToken = data.access_token;
        localStorage.setItem('raven_token', authToken);
        currentUser = data.user;
        
        hideLoginModal();
        updateUIForLoggedInUser();
        loadDashboardData();
        showToast('Login successful', 'success');
    } else {
        const error = await response.json();
        showToast(error.detail || 'Login failed', 'error');
    }
}

async function register(email, fullName, phoneNumber, password) {
    const response = await fetch(`${API_BASE_URL}/auth/register`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            email,
            full_name: fullName,
            phone_number: phoneNumber,
            password
        })
    });
    
    if (response.ok) {
        showToast('Registration successful! Please login.', 'success');
        // Switch to login tab
        switchAuthTab('login');
    } else {
        const error = await response.json();
        showToast(error.detail || 'Registration failed', 'error');
    }
}

function logout() {
    authToken = null;
    currentUser = null;
    localStorage.removeItem('raven_token');
    
    updateUIForLoggedOutUser();
    showLoginModal();
    showToast('Logged out successfully', 'success');
}

// UI Update Functions
function updateUIForLoggedInUser() {
    navAuth.innerHTML = `
        <div class="user-menu">
            <span class="user-name">${currentUser.full_name}</span>
            <button class="btn btn-text" id="logoutBtnNav">
                <i class="fas fa-sign-out-alt"></i>
            </button>
        </div>
    `;
    
    document.getElementById('logoutBtnNav').addEventListener('click', logout);
}

function updateUIForLoggedOutUser() {
    navAuth.innerHTML = `
        <button class="btn btn-primary" id="loginBtnNav">
            <i class="fas fa-sign-in-alt"></i>
            Login
        </button>
    `;
    
    document.getElementById('loginBtnNav').addEventListener('click', showLoginModal);
}

// Navigation
function navigateTo(sectionId) {
    sections.forEach(section => {
        section.classList.remove('active');
    });
    
    navLinks.forEach(link => {
        link.classList.remove('active');
    });
    
    document.getElementById(sectionId).classList.add('active');
    document.querySelector(`[href="#${sectionId}"]`).classList.add('active');
    
    // Load section-specific data
    if (sectionId === 'contacts') {
        loadEmergencyContacts();
    } else if (sectionId === 'sos') {
        loadSOSHistory();
    } else if (sectionId === 'profile') {
        loadProfileData();
    }
}

// Dashboard Functions
async function loadDashboardData() {
    loadEmergencyContacts();
    loadSOSHistory();
    loadProfileData();
}

async function loadEmergencyContacts() {
    const contacts = await apiRequest('/emergency-contacts/');
    const contactsGrid = document.getElementById('contactsGrid');
    const contactsCount = document.getElementById('contactsCount');
    
    if (contacts && contacts.length > 0) {
        contactsCount.textContent = contacts.length;
        
        contactsGrid.innerHTML = contacts.map(contact => `
            <div class="contact-card">
                <div class="contact-header">
                    <div class="contact-avatar">
                        <i class="fas fa-user"></i>
                    </div>
                    ${contact.is_primary ? '<span class="contact-primary">Primary</span>' : ''}
                </div>
                <div class="contact-name">${contact.name}</div>
                <div class="contact-relation">${formatRelation(contact.relation)}</div>
                <div class="contact-info">
                    <div class="contact-info-item">
                        <i class="fas fa-phone"></i>
                        <span>${contact.phone_number}</span>
                    </div>
                    ${contact.email ? `
                        <div class="contact-info-item">
                            <i class="fas fa-envelope"></i>
                            <span>${contact.email}</span>
                        </div>
                    ` : ''}
                </div>
                <div class="contact-verified">
                    <i class="fas ${contact.is_verified ? 'fa-check-circle' : 'fa-clock'}"></i>
                    ${contact.is_verified ? 'Verified' : 'Pending verification'}
                </div>
                <div class="contact-actions">
                    <button class="btn btn-secondary btn-sm" onclick="editContact(${contact.id})">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="btn btn-danger btn-sm" onclick="deleteContact(${contact.id})">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </div>
        `).join('');
    } else {
        contactsCount.textContent = '0';
        contactsGrid.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-user-plus"></i>
                <h3>No emergency contacts yet</h3>
                <p>Add trusted contacts who will be notified in case of emergency</p>
            </div>
        `;
    }
}

async function loadSOSHistory() {
    const sosEvents = await apiRequest('/sos/');
    const sosHistory = document.getElementById('sosHistory');
    const alertsCount = document.getElementById('alertsCount');
    
    if (sosEvents && sosEvents.length > 0) {
        alertsCount.textContent = sosEvents.length;
        
        sosHistory.innerHTML = sosEvents.map(event => `
            <div class="sos-history-item">
                <div>
                    <div class="sos-history-status ${event.status}">${formatStatus(event.status)}</div>
                    <div class="sos-history-time">${formatDateTime(event.created_at)}</div>
                </div>
                ${event.status === 'active' ? `
                    <button class="btn btn-danger btn-sm" onclick="cancelSOS(${event.id})">
                        Cancel
                    </button>
                ` : ''}
            </div>
        `).join('');
    } else {
        alertsCount.textContent = '0';
        sosHistory.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-history"></i>
                <h3>No SOS history</h3>
            </div>
        `;
    }
}

async function loadProfileData() {
    if (currentUser) {
        document.getElementById('profileName').textContent = currentUser.full_name;
        document.getElementById('profileEmail').textContent = currentUser.email;
        document.getElementById('fullName').value = currentUser.full_name;
        document.getElementById('phoneNumber').value = currentUser.phone_number || '';
        document.getElementById('bio').value = currentUser.bio || '';
        document.getElementById('notificationEnabled').checked = currentUser.notification_enabled;
        document.getElementById('locationSharingEnabled').checked = currentUser.location_sharing_enabled;
    }
}

// SOS Functions
async function createSOS() {
    if (!currentLocation) {
        showToast('Location not available. Please enable location services.', 'error');
        return;
    }
    
    const sosData = {
        latitude: currentLocation.latitude,
        longitude: currentLocation.longitude,
        location_accuracy: currentLocation.accuracy,
        address: currentLocation.address
    };
    
    const sosEvent = await apiRequest('/sos/', {
        method: 'POST',
        body: JSON.stringify(sosData)
    });
    
    if (sosEvent) {
        // Notify contacts
        await apiRequest(`/sos/${sosEvent.id}/notify`, {
            method: 'POST'
        });
        
        showToast('SOS sent successfully! Your contacts have been notified.', 'success');
        loadSOSHistory();
    }
}

async function cancelSOS(sosId) {
    const result = await apiRequest(`/sos/${sosId}/cancel`, {
        method: 'POST'
    });
    
    if (result) {
        showToast('SOS cancelled', 'success');
        loadSOSHistory();
    }
}

// Contact Functions
async function addContact(contactData) {
    const contact = await apiRequest('/emergency-contacts/', {
        method: 'POST',
        body: JSON.stringify(contactData)
    });
    
    if (contact) {
        showToast('Contact added successfully', 'success');
        hideAddContactModal();
        loadEmergencyContacts();
    }
}

async function deleteContact(contactId) {
    if (confirm('Are you sure you want to delete this contact?')) {
        const result = await apiRequest(`/emergency-contacts/${contactId}`, {
            method: 'DELETE'
        });
        
        if (result !== null) {
            showToast('Contact deleted', 'success');
            loadEmergencyContacts();
        }
    }
}

// Profile Functions
async function updateProfile(profileData) {
    const updatedUser = await apiRequest('/users/me', {
        method: 'PUT',
        body: JSON.stringify(profileData)
    });
    
    if (updatedUser) {
        currentUser = updatedUser;
        showToast('Profile updated successfully', 'success');
    }
}

// Location Functions
function getCurrentLocation() {
    if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
            (position) => {
                currentLocation = {
                    latitude: position.coords.latitude,
                    longitude: position.coords.longitude,
                    accuracy: position.coords.accuracy
                };
                
                updateLocationDisplay();
            },
            (error) => {
                console.error('Geolocation error:', error);
                showToast('Unable to get location. Please enable location services.', 'warning');
            }
        );
    } else {
        showToast('Geolocation is not supported by your browser', 'error');
    }
}

function updateLocationDisplay() {
    if (currentLocation) {
        const locationText = `${currentLocation.latitude.toFixed(6)}, ${currentLocation.longitude.toFixed(6)}`;
        document.getElementById('currentLocation').textContent = locationText;
        document.getElementById('sosConfirmLocation').textContent = locationText;
    }
}

// Modal Functions
function showLoginModal() {
    document.getElementById('loginModal').classList.add('active');
}

function hideLoginModal() {
    document.getElementById('loginModal').classList.remove('active');
}

function showAddContactModal() {
    document.getElementById('addContactModal').classList.add('active');
}

function hideAddContactModal() {
    document.getElementById('addContactModal').classList.remove('active');
}

function showSOSConfirmModal() {
    document.getElementById('sosConfirmModal').classList.add('active');
}

function hideSOSConfirmModal() {
    document.getElementById('sosConfirmModal').classList.remove('active');
}

// Tab Switching
function switchAuthTab(tab) {
    document.querySelectorAll('.auth-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.auth-form').forEach(f => f.classList.remove('active'));
    
    document.querySelector(`[data-tab="${tab}"]`).classList.add('active');
    document.getElementById(`${tab}Form`).classList.add('active');
}

// Utility Functions
function formatRelation(relation) {
    const relations = {
        family: 'Family',
        friend: 'Friend',
        partner: 'Partner',
        colleague: 'Colleague',
        neighbor: 'Neighbor',
        other: 'Other'
    };
    return relations[relation] || relation;
}

function formatStatus(status) {
    const statuses = {
        active: 'Active',
        resolved: 'Resolved',
        cancelled: 'Cancelled',
        false_alarm: 'False Alarm'
    };
    return statuses[status] || status;
}

function formatDateTime(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const diff = now - date;
    
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);
    
    if (minutes < 1) return 'Just now';
    if (minutes < 60) return `${minutes} minutes ago`;
    if (hours < 24) return `${hours} hours ago`;
    if (days < 7) return `${days} days ago`;
    
    return date.toLocaleDateString();
}

function showToast(message, type = 'info') {
    const toastContainer = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    const icons = {
        success: 'fa-check-circle',
        error: 'fa-exclamation-circle',
        warning: 'fa-exclamation-triangle',
        info: 'fa-info-circle'
    };
    
    toast.innerHTML = `
        <i class="fas ${icons[type]} toast-icon"></i>
        <span class="toast-message">${message}</span>
        <button class="toast-close" onclick="this.parentElement.remove()">
            <i class="fas fa-times"></i>
        </button>
    `;
    
    toastContainer.appendChild(toast);
    
    setTimeout(() => {
        toast.remove();
    }, 5000);
}

// Event Listeners
function setupEventListeners() {
    // Navigation
    navLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const sectionId = link.getAttribute('href').substring(1);
            navigateTo(sectionId);
        });
    });
    
    // Auth tabs
    document.querySelectorAll('.auth-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            switchAuthTab(tab.dataset.tab);
        });
    });
    
    // Login form
    document.getElementById('loginForm').addEventListener('submit', (e) => {
        e.preventDefault();
        const email = document.getElementById('loginEmail').value;
        const password = document.getElementById('loginPassword').value;
        login(email, password);
    });
    
    // Register form
    document.getElementById('registerForm').addEventListener('submit', (e) => {
        e.preventDefault();
        const email = document.getElementById('registerEmail').value;
        const fullName = document.getElementById('registerFullName').value;
        const phoneNumber = document.getElementById('registerPhone').value;
        const password = document.getElementById('registerPassword').value;
        register(email, fullName, phoneNumber, password);
    });
    
    // Modal close buttons
    document.getElementById('closeLoginModal').addEventListener('click', hideLoginModal);
    document.getElementById('closeAddContactModal').addEventListener('click', hideAddContactModal);
    document.getElementById('closeSosConfirmModal').addEventListener('click', hideSOSConfirmModal);
    
    // Add contact button
    document.getElementById('addContactBtn').addEventListener('click', showAddContactModal);
    
    // Add contact form
    document.getElementById('addContactForm').addEventListener('submit', (e) => {
        e.preventDefault();
        const contactData = {
            name: document.getElementById('contactName').value,
            phone_number: document.getElementById('contactPhone').value,
            email: document.getElementById('contactEmail').value,
            relation: document.getElementById('contactRelation').value,
            is_primary: document.getElementById('contactPrimary').checked
        };
        addContact(contactData);
    });
    
    // SOS buttons
    document.getElementById('quickSOSBtn').addEventListener('click', showSOSConfirmModal);
    document.getElementById('sosButton').addEventListener('click', showSOSConfirmModal);
    document.getElementById('confirmSOS').addEventListener('click', () => {
        hideSOSConfirmModal();
        createSOS();
    });
    document.getElementById('cancelSOS').addEventListener('click', hideSOSConfirmModal);
    
    // Profile save
    document.getElementById('saveProfileBtn').addEventListener('click', () => {
        const profileData = {
            full_name: document.getElementById('fullName').value,
            phone_number: document.getElementById('phoneNumber').value,
            bio: document.getElementById('bio').value,
            notification_enabled: document.getElementById('notificationEnabled').checked,
            location_sharing_enabled: document.getElementById('locationSharingEnabled').checked
        };
        updateProfile(profileData);
    });
    
    // Profile logout
    document.getElementById('logoutBtn').addEventListener('click', logout);
    
    // Close modals on outside click
    document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.classList.remove('active');
            }
        });
    });
}
