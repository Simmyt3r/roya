<?php
require_once '../includes/config.php';
require_once '../includes/database.php';
require_once '../includes/auth.php';

redirect_if_not_admin_logged_in();

$db = new Database();

// Handle hotel approval/rejection
if ($_SERVER['REQUEST_METHOD'] == 'POST' && isset($_POST['hotel_id'])) {
    $hotel_id = (int)$_POST['hotel_id'];
    $action = $_POST['action'];
    
    if ($action == 'approve') {
        $query = "UPDATE hotels SET is_verified = 1 WHERE id = :hotel_id";
        $message = "Hotel approved successfully!";
    } else if ($action == 'reject') {
        $query = "DELETE FROM hotels WHERE id = :hotel_id";
        $message = "Hotel rejected and removed successfully!";
    }
    
    $db->query($query);
    $db->bind(':hotel_id', $hotel_id);
    
    if ($db->execute()) {
        $success = $message;
    } else {
        $error = "Failed to process hotel. Please try again.";
    }
}

// Fetch unverified hotels
$query = "SELECT id, name, email, phone, city, country, registration_fee, created_at 
          FROM hotels WHERE is_verified = 0 ORDER BY created_at DESC";
$db->query($query);
$hotels = $db->resultSet();
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Approve Hotels - <?php echo SITE_NAME; ?></title>
    <link rel="stylesheet" href="../assets/css/style.css">
</head>
<body>
    <div class="container">
        <header>
            <h1><?php echo SITE_NAME; ?> - Admin Dashboard</h1>
            <nav>
                <ul>
                    <li><a href="dashboard.php">Dashboard</a></li>
                    <li><a href="approve_hotels.php">Approve Hotels</a></li>
                    <li><a href="manage_commissions.php">Manage Commissions</a></li>
                    <li><a href="reports.php">Reports</a></li>
                    <li><a href="../includes/auth.php?logout=1">Logout</a></li>
                </ul>
            </nav>
        </header>
        
        <h2>Approve Hotels</h2>
        
        <?php if (isset($success)): ?>
            <div class="success"><?php echo $success; ?></div>
        <?php endif; ?>
        
        <?php if (isset($error)): ?>
            <div class="error"><?php echo $error; ?></div>
        <?php endif; ?>
        
        <?php if (empty($hotels)): ?>
            <p>No hotels pending approval.</p>
        <?php else: ?>
            <table class="reservation-table">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Name</th>
                        <th>Email</th>
                        <th>Phone</th>
                        <th>Location</th>
                        <th>Registration Fee</th>
                        <th>Created At</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    <?php foreach ($hotels as $hotel): ?>
                        <tr>
                            <td><?php echo htmlspecialchars($hotel['id']); ?></td>
                            <td><?php echo htmlspecialchars($hotel['name']); ?></td>
                            <td><?php echo htmlspecialchars($hotel['email']); ?></td>
                            <td><?php echo htmlspecialchars($hotel['phone']); ?></td>
                            <td><?php echo htmlspecialchars($hotel['city']); ?>, <?php echo htmlspecialchars($hotel['country']); ?></td>
                            <td>$<?php echo htmlspecialchars($hotel['registration_fee']); ?></td>
                            <td><?php echo htmlspecialchars($hotel['created_at']); ?></td>
                            <td>
                                <form method="POST" action="" style="display: inline;">
                                    <input type="hidden" name="hotel_id" value="<?php echo $hotel['id']; ?>">
                                    <button type="submit" name="action" value="approve" class="btn">Approve</button>
                                </form>
                                <form method="POST" action="" style="display: inline;">
                                    <input type="hidden" name="hotel_id" value="<?php echo $hotel['id']; ?>">
                                    <button type="submit" name="action" value="reject" class="btn" style="background-color: #e74c3c;">Reject</button>
                                </form>
                            </td>
                        </tr>
                    <?php endforeach; ?>
                </tbody>
            </table>
        <?php endif; ?>
    </div>
</body>
</html>