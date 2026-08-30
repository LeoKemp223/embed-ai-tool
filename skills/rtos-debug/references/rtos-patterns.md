# RTOS 常见问题模式

## 栈溢出

**症状：**
- HardFault 且 SP 指向非法区域
- 任务行为异常后触发 HardFault
- 调用 `configASSERT` 触发的断言失败

**诊断：**
- 检查 `uxTaskGetStackHighWaterMark` 返回值（FreeRTOS）
- 查看 SP 寄存器是否在任务栈范围内
- 检查栈底是否被覆写（FreeRTOS 使用 `0xa5a5a5a5` 填充）

**修复：**
- 增大任务栈大小（`xTaskCreate` 的 `usStackDepth` 参数）
- 减少栈上大数组/结构体的使用
- 将大缓冲区改为 `static` 或 `pvPortMalloc` 分配

## 优先级反转

**症状：**
- 高优先级任务被长时间阻塞
- 系统响应延迟异常增大
- 低优先级任务持有互斥锁时被中等优先级抢占

**诊断：**
- 检查高优先级任务是否在等待低优先级任务持有的 mutex
- 查看 FreeRTOS 的优先级继承是否生效（使用 `xSemaphoreCreateMutex` 而非 `xSemaphoreCreateBinary`）

**修复：**
- 使用 `xSemaphoreCreateMutex`（支持优先级继承）
- 减少临界区持有时间
- 重新设计任务间通信避免共享资源

## 中断中使用非 ISR 安全 API

**症状：**
- 在中断处理函数中调用 FreeRTOS API 导致断言失败
- `configASSERT` 在 `xTaskResumeAll` 或类似函数中触发
- 不可预测的调度行为

**常见错误：**
```c
// ❌ 错误：在 ISR 中使用非 ISR 安全 API
void USART1_IRQHandler(void) {
    xSemaphoreGive(sem);  // 应使用 xSemaphoreGiveFromISR
}

// ✅ 正确
void USART1_IRQHandler(void) {
    BaseType_t xHigherPriorityTaskWoken = pdFALSE;
    xSemaphoreGiveFromISR(sem, &xHigherPriorityTaskWoken);
    portYIELD_FROM_ISR(xHigherPriorityTaskWoken);
}
```

## 各 RTOS 关键全局变量

### FreeRTOS

| 变量名 | 含义 |
|--------|------|
| `pxCurrentTCB` | 当前运行任务的 TCB 指针 |
| `pxReadyTasksLists` | 就绪任务列表数组（按优先级索引） |
| `xDelayedTaskList1` / `xDelayedTaskList2` | 延迟任务列表 |
| `xSuspendedTaskList` | 挂起任务列表 |
| `uxCurrentNumberOfTasks` | 当前任务总数 |
| `xQueueRegistry` | 队列注册表 |

### RT-Thread

| 变量名 | 含义 |
|--------|------|
| `rt_current_thread` | 当前运行线程指针 |
| `rt_thread_ready_priority_group` | 就绪优先级位图 |
| `rt_object_information` | 内核对象信息表 |

### Zephyr

| 变量名 | 含义 |
|--------|------|
| `_kernel.threads` | 线程链表头（指向第一个线程的指针，经 `next_thread` 串联） |
| `_kernel.cpus[i].current` | 第 i 个 CPU 当前运行线程 |
| `_kernel.ready_q` | 就绪队列 |
| `_track_list_k_msgq` 等 | `CONFIG_TRACING_OBJECT_TRACKING` 内核对象追踪链表头 |
| `_k_sem_list_start/_end` 等 | 静态定义内核对象段边界（链接脚本生成） |

### Zephyr thread_state 位（`base.thread_state`）

| 位 | 含义 |
|----|------|
| `0x01` | DUMMY（未初始化栈的线程） |
| `0x02` | PENDING（等待某个内核对象） |
| `0x04` | PRESTART（尚未开始运行） |
| `0x08` | DEAD |
| `0x10` | SUSPENDED |
| `0x80` | QUEUED（在就绪队列中） |

## Zephyr 死锁排查流程

1. 运行 `rtos_debugger.py --deadlock --elf build/zephyr.elf`，
   脚本会构建 mutex 等待者→持有者图并检测环。
2. 若报出等待环（如 `A -> B -> A`），用 `--queues` 查看每个 mutex
   的持有者与等待者，确认锁获取顺序。
3. 修复方式：统一加锁顺序，或改用 `k_mutex_lock` 超时参数（避免
   `K_FOREVER`）后重试。
