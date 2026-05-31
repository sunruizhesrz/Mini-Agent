const express = require('express');
const router = express.Router();
const controller = require('../controllers/admin.controller');

router.get('/', controller.getAll);
router.get('/:id', controller.getById);

module.exports = router;
