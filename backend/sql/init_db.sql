-- ================================================
-- 迭代看板数据库初始化脚本
-- 数据库: iterdb
-- ================================================

-- 创建数据库
CREATE DATABASE IF NOT EXISTS iterdb DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 创建数据库用户
CREATE USER IF NOT EXISTS 'iteruser'@'%' IDENTIFIED BY 'iterpass123';
CREATE USER IF NOT EXISTS 'iteruser'@'localhost' IDENTIFIED BY 'iterpass123';

-- 授权
GRANT ALL PRIVILEGES ON iterdb.* TO 'iteruser'@'%';
GRANT ALL PRIVILEGES ON iterdb.* TO 'iteruser'@'localhost';
