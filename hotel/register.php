<?php
require_once '../includes/config.php';
require_once '../includes/database.php';
require_once '../includes/auth.php';
$db = new Database();

if ($_SERVER['REQUEST_METHOD'] == 'POST') {
    $name = $_POST['name'];
    $email = $_POST['email'];
    $password = hash_password($_POST['password']);
    $phone = $_POST['phone'];
    $address = $_POST['address'];
    $city = $_POST['city'];
    $country = $_POST['country'];
    $registration_fee = $_POST['registration_fee'];
    
    $query = "INSERT INTO hotels (name, email, password, phone, address, city, country, registration_fee) 
              VALUES (:name, :email, :password, :phone, :address, :city, :country, :registration_fee)";
    
    $db->query($query);
    $db->bind(':name', $name);
    $db->bind(':email', $email);
    $db->bind(':password', $password);
    $db->bind(':phone', $phone);
    $db->bind(':address', $address);
    $db->bind(':city', $city);
    $db->bind(':country', $country);
    $db->bind(':registration_fee', $registration_fee);
    
    if ($db->execute()) {
        // Redirect to login page after successful registration
        header('Location: login.php?registered=true');
        exit;
    } else {
        $error = "Registration failed. Please try again.";
    }
}
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hotel Registration - <?php echo SITE_NAME; ?></title>
    <link rel="stylesheet" href="../assets/css/style.css">
</head>
<body>
    <div class="container">
        <h1>Hotel Registration</h1>
        
        <?php if (isset($error)): ?>
            <div class="error"><?php echo $error; ?></div>
        <?php endif; ?>
        
        <form method="POST" action="">
            <div class="form-group">
                <label for="name">Hotel Name *</label>
                <input type="text" id="name" name="name" required>
            </div>
            
            <div class="form-group">
                <label for="email">Email Address *</label>
                <input type="email" id="email" name="email" required>
            </div>
            
            <div class="form-group">
                <label for="password">Password *</label>
                <input type="password" id="password" name="password" required>
            </div>
            
            <div class="form-group">
                <label for="phone">Phone Number</label>
                <input type="tel" id="phone" name="phone">
            </div>
            
            <div class="form-group">
                <label for="address">Address</label>
                <textarea id="address" name="address"></textarea>
            </div>
            
            <div class="form-group">
                <label for="city">City *</label>
                <input type="text" id="city" name="city" required>
            </div>
            
            <div class="form-group">
                <label for="country">Country *</label>
                <input type="text" id="country" name="country" required>
            </div>
            
            <div class="form-group">
                <label for="registration_fee">Registration Plan *</label>
                <select id="registration_fee" name="registration_fee" required>
                    <option value="<?php echo BASIC_REGISTRATION_FEE; ?>">Basic Plan - $<?php echo BASIC_REGISTRATION_FEE; ?></option>
                    <option value="<?php echo PREMIUM_REGISTRATION_FEE; ?>">Premium Plan - $<?php echo PREMIUM_REGISTRATION_FEE; ?></option>
                </select>
            </div>
            
            <button type="submit">Register Hotel</button>
        </form>
        
        <p>Already have an account? <a href="login.php">Login here</a></p>
    </div>
</body>
</html>