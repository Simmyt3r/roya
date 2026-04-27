<?php
// Authentication functions
session_start();

function is_logged_in() {
    return isset($_SESSION['user_id']);
}

function is_hotel_logged_in() {
    return isset($_SESSION['hotel_id']);
}

function is_admin_logged_in() {
    return isset($_SESSION['admin_id']);
}

function redirect_if_not_logged_in() {
    if (!is_logged_in()) {
        header('Location: /user/login.php');
        exit;
    }
}

function redirect_if_not_hotel_logged_in() {
    if (!is_hotel_logged_in()) {
        header('Location: /hotel/login.php');
        exit;
    }
}

function redirect_if_not_admin_logged_in() {
    if (!is_admin_logged_in()) {
        header('Location: /admin/login.php');
        exit;
    }
}

function logout() {
    session_destroy();
    header('Location: /index.php');
    exit;
}

function hash_password($password) {
    return password_hash($password, PASSWORD_DEFAULT);
}

function verify_password($password, $hashed_password) {
    return password_verify($password, $hashed_password);
}
?>